import unittest
from unittest.mock import patch

from fastapi import HTTPException

from local_only_mcp import LocalOnlyMcpGuardrail


class LocalOnlyMcpGuardrailTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.guardrail = LocalOnlyMcpGuardrail()

    async def test_local_model_can_use_mcp(self):
        request = {
            "model": "local-ollama",
            "tools": [{"type": "function"}],
            "messages": [{"role": "user", "content": "Look up a device"}],
        }
        self.assertIs(
            await self.guardrail.async_pre_call_hook(None, None, request, "completion"),
            request,
        )

    async def test_cloud_model_with_tools_is_rejected(self):
        request = {
            "model": "copilot-auto",
            "tools": [{"type": "function"}],
            "messages": [{"role": "user", "content": "Look up a device"}],
        }
        with self.assertRaises(HTTPException) as raised:
            await self.guardrail.async_pre_call_hook(None, None, request, "completion")
        self.assertEqual(raised.exception.status_code, 403)

    async def test_opt_in_only_allows_copilot_tool_requests(self):
        request = {
            "model": "copilot-auto",
            "tools": [{"type": "function"}],
            "messages": [{"role": "user", "content": "Look up a device"}],
        }
        with patch.dict("os.environ", {"ALLOW_COPILOT_MCP": "true"}):
            self.assertIs(
                await self.guardrail.async_pre_call_hook(None, None, request, "completion"),
                request,
            )
            for model in ("other-cloud-model", "other-provider/copilot-auto"):
                request["model"] = model
                with self.assertRaises(HTTPException):
                    await self.guardrail.async_pre_call_hook(None, None, request, "completion")

    async def test_cloud_model_with_tool_result_is_rejected(self):
        request = {
            "model": "copilot-auto",
            "messages": [{"role": "tool", "content": "private result"}],
        }
        with self.assertRaises(HTTPException) as raised:
            await self.guardrail.async_pre_call_hook(None, None, request, "completion")
        self.assertEqual(raised.exception.status_code, 403)

    async def test_cloud_model_without_tools_is_allowed(self):
        request = {
            "model": "copilot-auto",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        self.assertIs(
            await self.guardrail.async_pre_call_hook(None, None, request, "completion"),
            request,
        )


if __name__ == "__main__":
    unittest.main()
