from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from main import (
    InstallationTokenProvider,
    MODEL_ID,
    StaticTokenProvider,
    _new_copilot_client,
    chat_completions,
    parse_messages,
    token_provider_from_environment,
)


class ParseMessagesTests(unittest.TestCase):
    def test_creates_client_with_explicit_session_auth_support(self):
        self.assertIsNotNone(_new_copilot_client())

    def test_builds_system_instructions_and_preserves_conversation(self):
        system, conversation = parse_messages({
            "model": MODEL_ID,
            "messages": [
                {"role": "system", "content": "Answer briefly."},
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
                {"role": "user", "content": "Again"},
            ],
        })
        self.assertIn("Answer briefly.", system)
        self.assertEqual(
            conversation,
            '[{"role": "user", "content": "Hello"}, '
            '{"role": "assistant", "content": "Hi"}, '
            '{"role": "user", "content": "Again"}]',
        )

    @patch.dict("os.environ", {"ALLOW_COPILOT_MCP": "false"})
    def test_rejects_mcp_tool_definitions_and_results_without_opt_in(self):
        for request in (
            {
                "model": MODEL_ID,
                "tools": [{"type": "function"}],
                "messages": [{"role": "user", "content": "Use a tool"}],
            },
            {
                "model": MODEL_ID,
                "messages": [
                    {"role": "user", "content": "Use a tool"},
                    {"role": "tool", "content": "private result"},
                ],
            },
        ):
            with self.subTest(request=request), self.assertRaises(HTTPException):
                parse_messages(request)

    @patch.dict("os.environ", {"ALLOW_COPILOT_MCP": "true"})
    def test_preserves_tool_calls_and_results_when_enabled(self):
        messages = [
            {"role": "user", "content": "Look up a device"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call-1", "type": "function",
                 "function": {"name": "lookup", "arguments": '{"id": 1}'}}
            ]},
            {"role": "tool", "tool_call_id": "call-1", "content": "device found"},
        ]
        _, conversation = parse_messages({"model": MODEL_ID, "messages": messages})
        self.assertEqual(json.loads(conversation), messages)

    def test_rejects_unknown_model(self):
        with self.assertRaises(HTTPException):
            parse_messages({
                "model": "another-model",
                "messages": [{"role": "user", "content": "Hello"}],
            })


class InstallationTokenProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_token_mode_uses_explicit_token_without_app_settings(self):
        with patch.dict(
            "os.environ",
            {"COPILOT_AUTH_MODE": "token", "COPILOT_GITHUB_TOKEN": "test-token"},
            clear=True,
        ):
            provider = token_provider_from_environment()
        self.assertEqual(await provider.get(), "test-token")

    async def test_completion_passes_token_to_copilot_session(self):
        session = AsyncMock()
        session.send_and_wait.return_value = SimpleNamespace(
            data=SimpleNamespace(content="response")
        )
        session.__aenter__.return_value = session
        session.__aexit__.return_value = None
        session.on = MagicMock()
        client = SimpleNamespace(create_session=AsyncMock(return_value=session))
        app = SimpleNamespace(state=SimpleNamespace(tokens=StaticTokenProvider("test-token"), copilot=client))
        with patch("main.app", app):
            result = await chat_completions({
                "model": MODEL_ID,
                "messages": [{"role": "user", "content": "Hello"}],
            })
        self.assertEqual(client.create_session.await_args.kwargs["github"], {"token": "test-token"})
        self.assertEqual(result["choices"][0]["message"]["content"], "response")

    @patch.dict("os.environ", {"ALLOW_COPILOT_MCP": "true"})
    async def test_tool_call_is_returned_for_client_execution(self):
        session = AsyncMock()
        session.__aenter__.return_value = session
        session.__aexit__.return_value = None
        session.on = MagicMock()
        client = SimpleNamespace(create_session=AsyncMock(return_value=session))

        async def send_and_wait(*args, **kwargs):
            tool = client.create_session.await_args.kwargs["tools"]["definitions"][0]
            self.assertTrue(tool.is_terminal)
            self.assertTrue(tool.skip_permission)
            await tool.handler(SimpleNamespace(
                tool_name="lookup", tool_call_id="call-1", arguments={"vdom": "example"}
            ))
            return SimpleNamespace(data=SimpleNamespace(content=None))

        session.send_and_wait.side_effect = send_and_wait
        app = SimpleNamespace(state=SimpleNamespace(
            tokens=StaticTokenProvider("test-token"), copilot=client
        ))
        request = {
            "model": MODEL_ID,
            "messages": [{"role": "user", "content": "Look up a device"}],
            "tools": [{
                "type": "function",
                "function": {"name": "lookup", "description": "Look up a device",
                             "parameters": {"type": "object"}},
            }],
        }
        with patch("main.app", app):
            response = await chat_completions(request)
        choice = response["choices"][0]
        self.assertEqual(choice["finish_reason"], "tool_calls")
        self.assertEqual(choice["message"]["tool_calls"][0], {
            "id": "call-1",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"vdom": "example"}'},
        })

        request["stream"] = True
        with patch("main.app", app):
            response = await chat_completions(request)
            events = [chunk async for chunk in response.body_iterator]
        self.assertTrue(any('"tool_calls"' in event for event in events))
        self.assertTrue(any('"finish_reason": "tool_calls"' in event for event in events))

    def test_authentication_modes_fail_closed(self):
        for environment, expected in (
            ({"COPILOT_AUTH_MODE": "token"}, "COPILOT_GITHUB_TOKEN"),
            ({"COPILOT_AUTH_MODE": "invalid"}, "COPILOT_AUTH_MODE"),
            ({}, "COPILOT_APP_ID"),
        ):
            with self.subTest(environment=environment), patch.dict("os.environ", environment, clear=True):
                with self.assertRaisesRegex(RuntimeError, expected):
                    token_provider_from_environment()

    def test_github_app_mode_uses_app_credentials(self):
        with patch.dict(
            "os.environ",
            {
                "COPILOT_AUTH_MODE": "github_app",
                "COPILOT_GITHUB_TOKEN": "ignored-token",
                "COPILOT_APP_ID": "app-id",
                "COPILOT_INSTALLATION_ID": "installation-id",
                "COPILOT_APP_PRIVATE_KEY_B64": "cGVt",
            },
            clear=True,
        ):
            provider = token_provider_from_environment()
        self.assertIsInstance(provider, InstallationTokenProvider)
        self.assertEqual(provider.private_key, "pem")

    @patch("main.jwt.encode", return_value="app-jwt")
    @patch("main.httpx.AsyncClient")
    async def test_caches_installation_token_and_refreshes_when_expired(
        self,
        async_client_factory,
        encode_jwt,
    ):
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

        class Response:
            is_error = False
            status_code = 201

            def __init__(self, token):
                self.token = token

            def json(self):
                return {"token": self.token, "expires_at": expiry}

        http_client = AsyncMock()
        http_client.post.side_effect = [Response("first-token"), Response("second-token")]
        context = AsyncMock()
        context.__aenter__.return_value = http_client
        async_client_factory.return_value = context
        provider = InstallationTokenProvider("app-id", "installation-id", "pem")

        self.assertEqual(await provider.get(), "first-token")
        self.assertEqual(await provider.get(), "first-token")
        provider._expires_at = 0
        self.assertEqual(await provider.get(), "second-token")
        self.assertEqual(http_client.post.await_count, 2)
        self.assertEqual(
            http_client.post.call_args.kwargs["json"],
            {"permissions": {"organization_copilot_requests": "read"}},
        )
        self.assertEqual(encode_jwt.call_count, 2)


if __name__ == "__main__":
    unittest.main()
