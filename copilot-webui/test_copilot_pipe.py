import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from copilot_pipe import _ApprovalBatcher, _make_tool, _messages, _stream_response


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
        delay = patch("copilot_pipe.TOOL_APPROVAL_BATCH_SECONDS", 0)
        delay.start()
        self.addCleanup(delay.stop)
        self.invoke = AsyncMock(return_value={"result": "ok"})
        self.entry = {
            "spec": {"description": "Test tool", "parameters": {"type": "object"}},
            "callable": self.invoke,
        }
        self.invocation = SimpleNamespace(arguments={"name": "example"})

    async def test_only_approved_calls_execute(self):
        event_call = AsyncMock(return_value={"action": "accept", "content": {}})
        tool = _make_tool("mcp_test", self.entry, _ApprovalBatcher(event_call))
        result = await tool.handler(self.invocation)
        self.invoke.assert_awaited_once_with(name="example")
        self.assertEqual(result.result_type, "success")
        event_call.assert_awaited_once_with({
            "type": "request:elicitation",
            "data": {
                "server_name": "Copilot tool approval",
                "mode": "form",
                "message": (
                    "Submit to allow all 1 listed tool call(s). Decline or cancel to reject them all.\n\n"
                    + json.dumps([{"tool": "mcp_test", "arguments": {"name": "example"}}], indent=2)
                ),
                "requestedSchema": {"type": "object", "properties": {}},
            },
        })

    async def test_parallel_calls_share_approval_and_later_calls_ask_again(self):
        requests = asyncio.Queue()

        async def event_call(event):
            decision = asyncio.get_running_loop().create_future()
            await requests.put((event, decision))
            return await decision

        approvals = _ApprovalBatcher(event_call)
        tool = _make_tool("mcp_test", self.entry, approvals)
        async with asyncio.timeout(2), asyncio.TaskGroup() as group:
            tasks = {
                name: group.create_task(tool.handler(SimpleNamespace(arguments={"name": name})))
                for name in ("first", "second")
            }
            event, decision = await requests.get()
            self.assertEqual(json.loads(event["data"]["message"].split("\n\n", 1)[1]), [
                {"tool": "mcp_test", "arguments": {"name": "first"}},
                {"tool": "mcp_test", "arguments": {"name": "second"}},
            ])
            late = group.create_task(tool.handler(SimpleNamespace(arguments={"name": "third"})))
            await asyncio.sleep(0)
            self.assertTrue(requests.empty())
            self.invoke.assert_not_awaited()
            decision.set_result({"action": "accept"})
            self.assertEqual((await tasks["first"]).result_type, "success")
            self.assertEqual((await tasks["second"]).result_type, "success")
            event, decision = await requests.get()
            self.assertEqual(json.loads(event["data"]["message"].split("\n\n", 1)[1]), [
                {"tool": "mcp_test", "arguments": {"name": "third"}},
            ])
            decision.set_result({"action": "decline"})
            self.assertEqual((await late).result_type, "denied")
        self.assertEqual([call.kwargs for call in self.invoke.await_args_list], [
            {"name": "first"},
            {"name": "second"},
        ])

    async def test_expired_approval_does_not_execute(self):
        async def no_response(event):
            await asyncio.Event().wait()

        with patch("copilot_pipe.TOOL_APPROVAL_TIMEOUT_SECONDS", 0.01):
            result = await _make_tool("mcp_test", self.entry, _ApprovalBatcher(no_response)).handler(self.invocation)
        self.assertEqual(result.result_type, "timeout")
        self.invoke.assert_not_awaited()

    async def test_denial_applies_to_the_whole_batch(self):
        tool = _make_tool("mcp_test", self.entry, _ApprovalBatcher(AsyncMock(return_value={"action": "decline"})))
        results = await asyncio.gather(tool.handler(self.invocation), tool.handler(self.invocation))
        self.assertEqual([result.result_type for result in results], ["denied", "denied"])
        self.invoke.assert_not_awaited()

    async def test_batch_uses_snapshot_and_includes_multiple_servers(self):
        requests = asyncio.Queue()
        decision = asyncio.get_running_loop().create_future()

        async def event_call(event):
            await requests.put(event)
            return await decision

        async with _ApprovalBatcher(event_call) as approvals:
            first = _make_tool("server1_read", self.entry, approvals)
            second_invoke = AsyncMock(return_value={"result": "ok"})
            second = _make_tool("server2_read", {**self.entry, "callable": second_invoke}, approvals)
            arguments = {"name": "before", "nested": {"value": "<tag> `code`\u202e"}}
            tasks = [
                asyncio.create_task(first.handler(SimpleNamespace(arguments=arguments))),
                asyncio.create_task(second.handler(SimpleNamespace(arguments={"name": "other"}))),
            ]
            event = await requests.get()
            message = event["data"]["message"]
            self.assertIn(r"\u202e", message)
            calls = json.loads(message.split("\n\n", 1)[1])
            self.assertEqual([call["tool"] for call in calls], ["server1_read", "server2_read"])
            arguments["nested"]["value"] = "changed"
            decision.set_result({"action": "accept"})
            self.assertEqual([result.result_type for result in await asyncio.gather(*tasks)], ["success", "success"])
            self.invoke.assert_awaited_once_with(**calls[0]["arguments"])
            second_invoke.assert_awaited_once_with(**calls[1]["arguments"])

    async def test_non_json_arguments_are_rejected(self):
        result = await _make_tool("mcp_test", self.entry, _ApprovalBatcher(AsyncMock())).handler(
            SimpleNamespace(arguments={"bad": float("nan")})
        )
        self.assertEqual(result.result_type, "failure")
        self.invoke.assert_not_awaited()

    async def test_cancellation_does_not_authorize_cancelled_call(self):
        ready = asyncio.Event()
        reply = asyncio.get_running_loop().create_future()

        async def event_call(event):
            ready.set()
            return await reply

        async with _ApprovalBatcher(event_call) as approvals:
            tool = _make_tool("mcp_test", self.entry, approvals)
            cancelled = asyncio.create_task(tool.handler(SimpleNamespace(arguments={"name": "cancelled"})))
            allowed = asyncio.create_task(tool.handler(SimpleNamespace(arguments={"name": "allowed"})))
            await ready.wait()
            cancelled.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await cancelled
            reply.set_result({"action": "accept"})
            self.assertEqual((await allowed).result_type, "success")
        self.invoke.assert_awaited_once_with(name="allowed")

    async def test_closing_batcher_cancels_pending_approval(self):
        ready = asyncio.Event()

        async def event_call(event):
            ready.set()
            await asyncio.Event().wait()

        async with _ApprovalBatcher(event_call) as approvals:
            tool = _make_tool("mcp_test", self.entry, approvals)
            task = asyncio.create_task(tool.handler(self.invocation))
            await ready.wait()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.invoke.assert_not_awaited()

    async def test_denial_and_disconnected_client_do_not_execute(self):
        for event_call in (None, AsyncMock(return_value={"action": "cancel"}), AsyncMock(return_value={"error": "disconnected"})):
            with self.subTest(event_call=event_call):
                result = await _make_tool("mcp_test", self.entry, _ApprovalBatcher(event_call)).handler(self.invocation)
                self.assertEqual(result.result_type, "denied")
        self.invoke.assert_not_awaited()

    async def test_invalid_arguments_do_not_execute(self):
        result = await _make_tool("mcp_test", self.entry, _ApprovalBatcher(AsyncMock(return_value=True))).handler(
            SimpleNamespace(arguments="not an object")
        )
        self.assertEqual(result.result_type, "failure")
        self.invoke.assert_not_awaited()

    async def test_fortios_404_reaches_copilot_as_failure_not_empty_results(self):
        from open_webui.utils.mcp.client import MCPClient

        async def invoke(**kwargs):
            return MCPClient.normalize_tool_result({
                "isError": False,
                "content": [{"type": "text", "text": "Private endpoint details"}],
                "structuredContent": {"error": "Private endpoint details", "status_code": 404},
            })

        self.entry["callable"] = AsyncMock(side_effect=invoke)
        event_call = AsyncMock(return_value={"action": "accept"})
        invocation = SimpleNamespace(arguments={"filter_expr": "private filter"})
        result = await _make_tool("fortios-mcp_log_query", self.entry, _ApprovalBatcher(event_call)).handler(invocation)
        self.assertEqual(result.result_type, "failure")
        payload = json.loads(result.text_result_for_llm)
        self.assertEqual(payload["http_status"], 404)
        self.assertEqual(payload["log_source"], "disk")
        self.assertIn("not a successful search", payload["message"])
        self.assertNotIn("Private endpoint details", result.text_result_for_llm)
        self.assertNotIn("private filter", result.text_result_for_llm)
        self.entry["callable"].assert_awaited_once()
        event_call.assert_awaited_once()

    async def test_rate_limit_retains_code_and_retry_delay_but_not_raw_error(self):
        from open_webui.utils.mcp.client import MCPClient

        async def invoke(**kwargs):
            return MCPClient.normalize_tool_result({
                "content": [{"type": "text", "text": "Private upstream body"}],
                "structuredContent": {"http_status": 429, "retry_after": "30"},
            })

        self.entry["callable"] = AsyncMock(side_effect=invoke)
        result = await _make_tool("mcp_test", self.entry, _ApprovalBatcher(AsyncMock(return_value={"action": "accept"}))).handler(self.invocation)
        self.assertEqual(result.result_type, "failure")
        self.assertEqual(json.loads(result.text_result_for_llm), {
            "message": "HTTP 429 Too Many Requests",
            "http_status": 429,
            "retry_after_seconds": 30,
        })

    async def test_protocol_error_and_timeout_are_not_successes(self):
        from mcp.shared.exceptions import MCPError
        from mcp_types import REQUEST_TIMEOUT
        from open_webui.utils.mcp.client import MCPClient

        async def protocol_error(**kwargs):
            return MCPClient.normalize_tool_result({
                "isError": True,
                "content": [{"type": "text", "text": "Tool failed"}],
            })

        for side_effect, expected in ((protocol_error, "failure"), (MCPError(REQUEST_TIMEOUT, "timeout"), "timeout")):
            with self.subTest(expected=expected):
                self.entry["callable"] = AsyncMock(side_effect=side_effect)
                event_call = AsyncMock(return_value={"action": "accept"})
                result = await _make_tool("mcp_test", self.entry, _ApprovalBatcher(event_call)).handler(self.invocation)
                self.assertEqual(result.result_type, expected)
                if expected == "timeout":
                    self.assertEqual(json.loads(result.text_result_for_llm)["mcp_code"], REQUEST_TIMEOUT)
                self.entry["callable"].assert_awaited_once()


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
