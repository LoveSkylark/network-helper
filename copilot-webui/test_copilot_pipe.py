import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from copilot_pipe import _make_tool, _messages, _stream_response


class ConversationTests(unittest.TestCase):
    def test_preserves_message_roles_and_system_prompt(self):
        system, conversation = _messages({
            "messages": [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
                {"role": "user", "content": "Continue"},
            ]
        })
        self.assertEqual(system, "Be concise.")
        self.assertIn('"role": "assistant", "content": "Hi"', conversation)
        self.assertIn('"role": "user", "content": "Continue"', conversation)

    def test_rejects_non_text_content(self):
        with self.assertRaisesRegex(ValueError, "text messages only"):
            _messages({"messages": [
                {"role": "user", "content": [{"type": "image_url", "image_url": {}}]}
            ]})


class ToolApprovalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.invoke = AsyncMock(return_value={"result": "ok"})
        self.entry = {
            "spec": {"description": "Test tool", "parameters": {"type": "object"}},
            "callable": self.invoke,
        }
        self.invocation = SimpleNamespace(arguments={"name": "example"})

    async def test_only_approved_calls_execute(self):
        event_call = AsyncMock(return_value=True)
        tool = _make_tool("mcp_test", self.entry, event_call)
        result = await tool.handler(self.invocation)
        self.invoke.assert_awaited_once_with(name="example")
        self.assertEqual(result.result_type, "success")
        self.assertIn("example", event_call.await_args.args[0]["data"]["message"])

    async def test_denial_and_disconnected_client_do_not_execute(self):
        for event_call in (None, AsyncMock(return_value=False), AsyncMock(return_value={"error": "disconnected"})):
            with self.subTest(event_call=event_call):
                result = await _make_tool("mcp_test", self.entry, event_call).handler(self.invocation)
                self.assertEqual(result.result_type, "denied")
        self.invoke.assert_not_awaited()

    async def test_invalid_arguments_do_not_execute(self):
        result = await _make_tool("mcp_test", self.entry, AsyncMock(return_value=True)).handler(
            SimpleNamespace(arguments="not an object")
        )
        self.assertEqual(result.result_type, "failure")
        self.invoke.assert_not_awaited()


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_streams_deltas_in_order(self):
        timeouts = []

        class FakeSession:
            def on(self, handler):
                self.handler = handler

            async def send_and_wait(self, conversation, timeout):
                timeouts.append(timeout)
                for content in ("Hello", " there"):
                    self.handler(SimpleNamespace(
                        type="assistant.message_delta",
                        agent_id=None,
                        data=SimpleNamespace(delta_content=content),
                    ))
                return SimpleNamespace(data=SimpleNamespace(content="Hello there"))

        chunks = [
            chunk async for chunk in _stream_response(FakeSession(), "prompt")
        ]
        self.assertEqual(chunks, ["Hello", " there"])
        self.assertEqual(timeouts, [600])

    async def test_falls_back_to_complete_response_without_deltas(self):
        class FakeSession:
            def on(self, handler):
                self.handler = handler

            async def send_and_wait(self, conversation, timeout):
                return SimpleNamespace(data=SimpleNamespace(content="Complete answer"))

        chunks = [
            chunk async for chunk in _stream_response(FakeSession(), "prompt")
        ]
        self.assertEqual(chunks, ["Complete answer"])


class MCPStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_configured_backends_forward_informational_text(self):
        from open_webui.utils.mcp.client import MCPClient

        emit = AsyncMock()
        client = MCPClient(server_name="librenms-mcp", event_emitter=emit)
        await client.emit_log_status(SimpleNamespace(level="debug", data="Diagnostic log"))
        await client.emit_log_status(SimpleNamespace(level="info", data={"extra": {"ignored": True}}))
        await client.emit_log_status(SimpleNamespace(
            level="info", data={"msg": "Listing devices...", "extra": {"ignored": True}},
        ))
        other_client = MCPClient(server_name="custom-mcp", event_emitter=emit)
        await other_client.emit_log_status(SimpleNamespace(level="info", data="Other server"))
        emit.assert_awaited_once_with({
            "type": "status",
            "data": {
                "action": "mcp_tool", "description": "LibreNMS: Listing devices...",
                "done": False, "error": False,
            },
        })

    async def test_emits_progress_then_reports_structured_authentication_error(self):
        from mcp_status import call_with_status

        emit = AsyncMock()
        result = {"structuredContent": {"error": "HTTP 403: private detail"}}

        async def call(progress):
            await progress(1, 2, "Querying...")
            return result

        self.assertIs(await call_with_status(emit, "cisco-aci-mcp", "read", call), result)
        start, progress, end = [args[0]["data"] for args, _ in emit.await_args_list]
        self.assertEqual(start["description"], "Cisco ACI: Running read...")
        self.assertEqual(progress["description"], "Cisco ACI: read: Querying...")
        self.assertTrue(end["done"] and end["error"])
        self.assertIn("HTTP 403", end["description"])
        self.assertNotIn("private detail", end["description"])

    async def test_sdk_timeout_is_reported_without_replaying_call(self):
        from mcp.shared.exceptions import MCPError
        from mcp_types import REQUEST_TIMEOUT
        from mcp_status import call_with_status

        emit = AsyncMock()
        call = AsyncMock(side_effect=MCPError(REQUEST_TIMEOUT, "private detail"))
        with self.assertRaises(MCPError):
            await call_with_status(emit, "fortios-mcp", "example", call)
        call.assert_awaited_once()
        self.assertEqual(
            emit.await_args.args[0]["data"]["description"],
            "FortiOS: example timed out; it was not retried.",
        )

    async def test_upstream_timeout_is_reported_without_exposing_raw_error(self):
        from mcp_status import call_with_status

        emit = AsyncMock()
        call = AsyncMock(return_value={
            "isError": True, "content": [{"type": "text", "text": "ConnectTimeout reaching private host"}],
        })
        await call_with_status(emit, "netbox-mcp", "read", call)
        status = emit.await_args.args[0]["data"]
        self.assertIn("upstream request timed out", status["description"])
        self.assertNotIn("private host", status["description"])
        self.assertTrue(status["done"] and status["error"])


if __name__ == "__main__":
    unittest.main()
