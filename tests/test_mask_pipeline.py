import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml


ROOT = Path(__file__).resolve().parent.parent
TEST_IP = "192.0.2.123"
TEST_EMAIL = "jane.doe@example.com"
TEST_PERSON = "Jane Doe"
TEST_IP_SECOND = "198.51.100.27"
TEST_EMAIL_SECOND = "john.smith@example.com"
TEST_PERSON_SECOND = "John Smith"
TOKEN = re.compile(r"<(?:IP_[0-9a-f]{10,64}|(?:PERSON|EMAIL_ADDRESS|PHONE_NUMBER)_\d+)>")
TEST_RESULTS = [
    {"subnet": f"{TEST_IP}/24", "owner": TEST_PERSON, "email": TEST_EMAIL},
    {"subnet": f"{TEST_IP_SECOND}/25", "owner": TEST_PERSON_SECOND, "email": TEST_EMAIL_SECOND},
]


def build_test_gateway_config(model_port):
    with (ROOT / "litellm/config.yaml").open(encoding="utf-8") as source:
        config = yaml.safe_load(source)
    copilot = next(model for model in config["model_list"] if model["model_name"] == "copilot-auto")
    copilot["litellm_params"]["api_base"] = f"http://127.0.0.1:{model_port}/v1"
    copilot["litellm_params"]["api_key"] = "test-adapter-key"
    config["model_list"] = [copilot]
    config["general_settings"] = {"master_key": "sk-test-gateway-key"}
    return config


class MaskPipelineConfigurationTests(unittest.TestCase):
    def test_test_gateway_uses_real_guardrails_and_only_local_mock(self):
        config = build_test_gateway_config(12345)
        self.assertEqual(len(config["model_list"]), 1)
        self.assertEqual(config["model_list"][0]["litellm_params"]["api_base"], "http://127.0.0.1:12345/v1")
        self.assertEqual(
            [guardrail["guardrail_name"] for guardrail in config["guardrails"]],
            ["local-only-mcp", "stable-mask", "presidio-mask"],
        )
        self.assertTrue(all(guardrail["litellm_params"]["default_on"] for guardrail in config["guardrails"]))
        presidio = next(guardrail for guardrail in config["guardrails"] if guardrail["guardrail_name"] == "presidio-mask")
        self.assertEqual(presidio["litellm_params"]["mode"], "pre_call")
        self.assertEqual(presidio["litellm_params"]["presidio_filter_scope"], "input")
        self.assertTrue(presidio["litellm_params"]["output_parse_pii"])


@unittest.skipUnless(os.environ.get("MASK_PIPELINE_INTEGRATION") == "1", "requires isolated test services")
class MaskPipelineIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.received = []

        class ModelHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                cls.received.append(request)
                messages = json.dumps(request["messages"], ensure_ascii=False)
                tool_results = [json.loads(message["content"]) for message in request["messages"] if message.get("role") == "tool"]
                result = json.dumps({"results": tool_results})
                if "change-placeholders" in messages:
                    result = TOKEN.sub(lambda match: "[redacted]" if match.group().startswith("<IP_") else "<PERSON>", result)
                if request.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for offset in range(0, len(result), 3):
                        payload = {
                            "id": "chatcmpl-mock", "object": "chat.completion.chunk", "created": 1,
                            "model": "copilot-auto", "choices": [{"index": 0, "delta": {"content": result[offset:offset + 3]}, "finish_reason": None}],
                        }
                        self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
                        self.wfile.flush()
                    payload = {
                        "id": "chatcmpl-mock", "object": "chat.completion.chunk", "created": 1,
                        "model": "copilot-auto", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    }
                    self.wfile.write(f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n".encode())
                else:
                    payload = {
                        "id": "chatcmpl-mock", "object": "chat.completion", "created": 1,
                        "model": "copilot-auto", "choices": [{"index": 0, "message": {"role": "assistant", "content": result}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    }
                    body = json.dumps(payload).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        cls.model = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
        cls.model_thread = threading.Thread(target=cls.model.serve_forever, daemon=True)
        cls.model_thread.start()
        cls.addClassCleanup(cls.model.server_close)
        cls.addClassCleanup(cls.model_thread.join)
        cls.addClassCleanup(cls.model.shutdown)

        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        config_path = Path(cls.temporary.name) / "config.yaml"
        config_path.write_text(yaml.safe_dump(build_test_gateway_config(cls.model.server_port)), encoding="utf-8")
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            cls.gateway_port = available.getsockname()[1]
        environment = dict(os.environ, ALLOW_COPILOT_MCP="true", NO_PROXY="*")
        cls.gateway = subprocess.Popen(
            ["litellm", "--config", str(config_path), "--host", "127.0.0.1", "--port", str(cls.gateway_port)],
            cwd="/app", env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cls.addClassCleanup(cls.stop_gateway)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if cls.gateway.poll() is not None:
                raise RuntimeError("Isolated LiteLLM gateway exited during startup")
            try:
                with urlopen(f"http://127.0.0.1:{cls.gateway_port}/health/liveliness", timeout=2):
                    return
            except (OSError, URLError):
                threading.Event().wait(0.5)
        raise RuntimeError("Isolated LiteLLM gateway did not become ready")

    @classmethod
    def stop_gateway(cls):
        cls.gateway.terminate()
        try:
            cls.gateway.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.gateway.kill()
            cls.gateway.wait()

    def setUp(self):
        self.received.clear()

    def request(self, *, stream=False, altered=False):
        payload = {
            "model": "copilot-auto",
            "stream": stream,
            "messages": [
                {"role": "user", "content": "Summarize the synthetic tool result." + (" change-placeholders" if altered else "")},
                {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "call-first", "type": "function", "function": {"name": "read_network", "arguments": "{}"}},
                    {"id": "call-second", "type": "function", "function": {"name": "read_network", "arguments": "{}"}},
                ]},
                {"role": "tool", "tool_call_id": "call-first", "content": json.dumps(TEST_RESULTS[0])},
                {"role": "tool", "tool_call_id": "call-second", "content": json.dumps(TEST_RESULTS[1])},
            ],
            "tools": [{"type": "function", "function": {"name": "read_network", "parameters": {"type": "object", "properties": {}}}}],
        }
        request = Request(
            f"http://127.0.0.1:{self.gateway_port}/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer sk-test-gateway-key"},
        )
        try:
            with urlopen(request, timeout=90) as response:
                body = response.read().decode()
        except HTTPError as error:
            self.fail(f"Isolated gateway returned HTTP {error.code}: {error.read().decode()[:2000]}")
        self.assertEqual(len(self.received), 1)
        if not stream:
            return json.loads(body)["choices"][0]["message"]["content"]
        chunks = [json.loads(line[5:].strip()) for line in body.splitlines() if line.startswith("data:") and line[5:].strip() != "[DONE]"]
        return "".join(choice.get("delta", {}).get("content") or "" for chunk in chunks for choice in chunk.get("choices", []))

    def assert_masked_upstream(self):
        upstream = json.dumps(self.received[0], ensure_ascii=False)
        for value in (TEST_IP, TEST_EMAIL, TEST_PERSON, TEST_IP_SECOND, TEST_EMAIL_SECOND, TEST_PERSON_SECOND):
            self.assertNotIn(value, upstream, "Synthetic sensitive value reached the mock model")
        self.assertRegex(upstream, r"<IP_[0-9a-f]{10,64}>")
        self.assertRegex(upstream, r"<EMAIL_ADDRESS_\d+>")
        self.assertRegex(upstream, r"<PERSON_\d+>")

    def test_exact_placeholders_restore_nonstreaming(self):
        response = self.request()
        self.assert_masked_upstream()
        self.assertEqual(json.loads(response)["results"], TEST_RESULTS)
        self.assertNotRegex(response, TOKEN)

    def test_exact_placeholders_restore_streaming(self):
        response = self.request(stream=True)
        self.assert_masked_upstream()
        self.assertEqual(json.loads(response)["results"], TEST_RESULTS)
        self.assertNotRegex(response, TOKEN)

    def test_changed_placeholders_are_not_falsely_restored(self):
        response = self.request(altered=True)
        self.assert_masked_upstream()
        results = json.loads(response)["results"]
        self.assertEqual([item["subnet"] for item in results], ["[redacted]/24", "[redacted]/25"])
        self.assertEqual([item["owner"] for item in results], ["<PERSON>", "<PERSON>"])


if __name__ == "__main__":
    unittest.main()