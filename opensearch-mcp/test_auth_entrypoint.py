import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from auth_entrypoint import api_key_headers, configured_environment


class OpenSearchAuthModeTests(unittest.TestCase):
    def test_basic_mode_keeps_credentials_and_disables_header_auth(self):
        result = configured_environment({
            "OPENSEARCH_USERNAME": "reader",
            "OPENSEARCH_PASSWORD": "password",
            "OPENSEARCH_TOKEN": "unused-token",
            "OPENSEARCH_HEADER_AUTH": "true",
        })
        self.assertEqual(result["OPENSEARCH_HEADER_AUTH"], "false")
        self.assertEqual(result["OPENSEARCH_USERNAME"], "reader")
        self.assertEqual(result["OPENSEARCH_PASSWORD"], "password")
        self.assertNotIn("OPENSEARCH_TOKEN", result)

    def test_token_mode_disables_basic_fallback(self):
        result = configured_environment({
            "OPENSEARCH_AUTH_MODE": "token",
            "OPENSEARCH_USERNAME": "reader",
            "OPENSEARCH_PASSWORD": "password",
            "OPENSEARCH_TOKEN": "token-value",
        })
        self.assertEqual(result["OPENSEARCH_HEADER_AUTH"], "true")
        self.assertNotIn("OPENSEARCH_USERNAME", result)
        self.assertNotIn("OPENSEARCH_PASSWORD", result)
        self.assertNotIn("OPENSEARCH_TOKEN", result)

    def test_token_mode_rejects_missing_or_invalid_tokens(self):
        for token in ("", "has spaces", "has\nnewline"):
            with self.subTest(token=token), self.assertRaises(ValueError):
                configured_environment({"OPENSEARCH_AUTH_MODE": "token", "OPENSEARCH_TOKEN": token})

    def test_api_key_mode_enables_headers_without_basic_fallback(self):
        result = configured_environment({
            "OPENSEARCH_AUTH_MODE": "api_key",
            "OPENSEARCH_USERNAME": "reader",
            "OPENSEARCH_PASSWORD": "password",
            "OPENSEARCH_TOKEN": "token-value",
        })
        self.assertEqual(result["OPENSEARCH_HEADER_AUTH"], "true")
        self.assertNotIn("OPENSEARCH_USERNAME", result)
        self.assertNotIn("OPENSEARCH_PASSWORD", result)
        self.assertNotIn("OPENSEARCH_TOKEN", result)

    def test_api_key_mode_translates_bearer_header(self):
        get_headers = api_key_headers(lambda: {"bearer_auth_header": "Bearer token-value"})
        self.assertEqual(get_headers()["bearer_auth_header"], "ApiKey token-value")
        get_headers = api_key_headers(lambda: {"bearer_auth_header": None})
        self.assertIsNone(get_headers()["bearer_auth_header"])

    @unittest.skipUnless(importlib.util.find_spec("opensearch"), "upstream MCP package is not installed")
    def test_api_key_reaches_upstream_client_with_url_prefix(self):
        import opensearch.client

        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path, self.headers.get("Authorization")))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)

        environment = {
            "OPENSEARCH_URL": f"http://127.0.0.1:{server.server_port}/custom-prefix",
            "OPENSEARCH_HEADER_AUTH": "true",
        }
        headers = api_key_headers(lambda: {"bearer_auth_header": "Bearer dummy-token"})
        with patch.dict("os.environ", environment, clear=True), \
             patch.object(opensearch.client, "_get_auth_from_headers", headers), \
             patch.object(opensearch.client, "get_aws_region_single_mode", return_value=None):
            async def check():
                client = opensearch.client._initialize_client_single_mode()
                try:
                    await client.cluster.health()
                finally:
                    await client.close()

            asyncio.run(check())

        self.assertEqual(requests, [("/custom-prefix/_cluster/health", "ApiKey dummy-token")])

    @unittest.skipUnless(importlib.util.find_spec("opensearch"), "upstream MCP package is not installed")
    def test_api_key_mode_handles_an_mcp_tool_call(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path, self.headers.get("Authorization")))
                payload = json.dumps({"version": {"number": "3.7.0"}, "status": "green"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)

        environment = dict(__import__("os").environ)
        environment.update({
            "OPENSEARCH_URL": f"http://127.0.0.1:{server.server_port}/custom-prefix",
            "OPENSEARCH_AUTH_MODE": "api_key",
            "OPENSEARCH_TOKEN": "dummy-token",
        })
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("auth_entrypoint.py"))],
            env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.addCleanup(process.wait)
        self.addCleanup(process.terminate)
        opener = build_opener(ProxyHandler({}))
        url = "http://127.0.0.1:9900/mcp"
        deadline = time.monotonic() + 20
        while True:
            try:
                opener.open(url, timeout=1).close()
                break
            except HTTPError:
                break
            except URLError:
                if process.poll() is not None or time.monotonic() >= deadline:
                    self.fail("MCP server did not start")
                threading.Event().wait(0.1)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer dummy-token",
        }

        def request(body):
            with opener.open(Request(url, json.dumps(body).encode(), headers), timeout=10) as response:
                session = response.headers.get("Mcp-Session-Id")
                if session:
                    headers["Mcp-Session-Id"] = session
                data = response.read().decode()
                if not data:
                    return {}
                if response.headers.get_content_type() == "text/event-stream":
                    data = next(line[5:].strip() for line in data.splitlines() if line.startswith("data:"))
                return json.loads(data)

        request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        }})
        request({"jsonrpc": "2.0", "method": "notifications/initialized"})
        result = request({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "GenericOpenSearchApiTool", "arguments": {"path": "/_cluster/health"},
        }})
        self.assertNotIn("error", result)
        self.assertFalse(result["result"].get("isError"), result)
        self.assertIn(("/custom-prefix/_cluster/health", "ApiKey dummy-token"), requests)

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            configured_environment({"OPENSEARCH_AUTH_MODE": "other"})


if __name__ == "__main__":
    unittest.main()