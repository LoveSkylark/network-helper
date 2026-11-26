import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hmac
import json
import os
import time
from typing import Any
from uuid import uuid4

import httpx
import jwt
from copilot import CopilotClient, RuntimeConnection, Tool, ToolResult
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


MODEL_ID = "copilot-auto"
COPILOT_TIMEOUT_SECONDS = 600
GITHUB_API_VERSION = "2022-11-28"


class StaticTokenProvider:
    def __init__(self, token: str) -> None:
        self.token = token

    async def get(self) -> str:
        return self.token


class InstallationTokenProvider:
    def __init__(self, app_id: str, installation_id: str, private_key: str) -> None:
        self.app_id = app_id
        self.installation_id = installation_id
        self.private_key = private_key
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    @classmethod
    def from_environment(cls) -> "InstallationTokenProvider":
        required = (
            "COPILOT_APP_ID",
            "COPILOT_INSTALLATION_ID",
            "COPILOT_APP_PRIVATE_KEY_B64",
        )
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise RuntimeError(f"Missing GitHub App settings: {', '.join(missing)}.")
        try:
            private_key = base64.b64decode(
                os.environ["COPILOT_APP_PRIVATE_KEY_B64"],
                validate=True,
            ).decode()
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("COPILOT_APP_PRIVATE_KEY_B64 must be base64-encoded PEM.") from exc
        return cls(
            os.environ["COPILOT_APP_ID"],
            os.environ["COPILOT_INSTALLATION_ID"],
            private_key,
        )

    async def get(self) -> str:
        if self._token and self._expires_at > time.time() + 300:
            return self._token
        async with self._lock:
            if self._token and self._expires_at > time.time() + 300:
                return self._token
            now = datetime.now(timezone.utc)
            app_jwt = jwt.encode(
                {
                    "iat": int((now - timedelta(seconds=60)).timestamp()),
                    "exp": int((now + timedelta(minutes=8)).timestamp()),
                    "iss": self.app_id,
                },
                self.private_key,
                algorithm="RS256",
            )
            url = (
                "https://api.github.com/app/installations/"
                f"{self.installation_id}/access_tokens"
            )
            headers = {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {app_jwt}",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            }
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json={"permissions": {"organization_copilot_requests": "read"}},
                )
            if response.is_error:
                raise RuntimeError(
                    f"GitHub App token exchange failed with HTTP {response.status_code}."
                )
            payload = response.json()
            token = payload.get("token")
            expires_at = payload.get("expires_at")
            if not isinstance(token, str) or not isinstance(expires_at, str):
                raise RuntimeError("GitHub App token response was missing required fields.")
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()
            self._token = token
            self._expires_at = expiry
            return token


def token_provider_from_environment() -> StaticTokenProvider | InstallationTokenProvider:
    mode = os.environ.get("COPILOT_AUTH_MODE", "github_app")
    if mode == "github_app":
        return InstallationTokenProvider.from_environment()
    if mode == "token":
        token = os.environ.get("COPILOT_GITHUB_TOKEN")
        if not token:
            raise RuntimeError("COPILOT_GITHUB_TOKEN is required for token authentication.")
        return StaticTokenProvider(token)
    raise RuntimeError("COPILOT_AUTH_MODE must be 'github_app' or 'token'.")


def parse_messages(body: dict[str, Any]) -> tuple[str, str]:
    if body.get("model") != MODEL_ID:
        raise HTTPException(status_code=404, detail="Unknown Copilot model.")
    if body.get("functions"):
        raise HTTPException(status_code=400, detail="Legacy functions are not supported.")
    allow_tools = os.environ.get("ALLOW_COPILOT_MCP", "false").lower() == "true"
    if not allow_tools and (
        body.get("tools") or body.get("tool_choice") not in (None, "none")
    ):
        raise HTTPException(
            status_code=400,
            detail="Copilot cloud requests cannot include tools; use a local model for MCP.",
        )
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="A non-empty messages list is required.")

    system_messages = []
    conversation = []
    for message in messages:
        if not isinstance(message, dict):
            raise HTTPException(status_code=400, detail="Unsupported chat message.")
        role = message.get("role")
        content = message.get("content")
        if not allow_tools and (role in ("tool", "function") or message.get("tool_calls")):
            raise HTTPException(
                status_code=400,
                detail="MCP tool conversations are local-only; select a local model.",
            )
        if isinstance(content, list):
            if any(not isinstance(part, dict) or part.get("type") != "text" for part in content):
                raise HTTPException(status_code=400, detail="Text-only messages are supported.")
            content = "\n".join(part.get("text", "") for part in content)
        if content is not None and not isinstance(content, str):
            raise HTTPException(status_code=400, detail="Unsupported chat message content.")
        if role == "system":
            system_messages.append(content or "")
        elif role in ("user", "assistant", "tool"):
            item = {"role": role, "content": content}
            if role == "assistant" and message.get("tool_calls"):
                if not isinstance(message["tool_calls"], list):
                    raise HTTPException(status_code=400, detail="Invalid assistant tool calls.")
                item["tool_calls"] = message["tool_calls"]
            if role == "tool":
                if not isinstance(message.get("tool_call_id"), str):
                    raise HTTPException(status_code=400, detail="Tool result requires a tool_call_id.")
                item["tool_call_id"] = message["tool_call_id"]
            conversation.append(item)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported message role: {role}.")
    if not any(message["role"] == "user" for message in conversation):
        raise HTTPException(status_code=400, detail="At least one user message is required.")

    instructions = (
        "The user message contains the conversation as a JSON array. Interpret the role "
        "labels and respond to the latest user message, incorporating any subsequent "
        "assistant tool calls and tool results."
    )
    if system_messages:
        instructions += "\n\n" + "\n\n".join(system_messages)
    return instructions, json.dumps(conversation, ensure_ascii=False)


def _completion(
    content: str | None, completion_id: str, created: int,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _chunk(completion_id: str, created: int, delta: dict[str, Any], finish_reason=None):
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": MODEL_ID,
        "choices": [
            {"index": 0, "delta": delta, "finish_reason": finish_reason}
        ],
    }


def _requested_tools(body: dict[str, Any], calls: list[dict[str, Any]]) -> list[Tool]:
    definitions = body.get("tools")
    if definitions is None:
        definitions = []
    if not isinstance(definitions, list):
        raise HTTPException(status_code=400, detail="Tools must be a list.")
    choice = body.get("tool_choice")
    if choice not in (None, "auto", "none"):
        raise HTTPException(status_code=400, detail="Only automatic tool selection is supported.")
    if choice == "none":
        return []

    tools = []
    names = set()
    for definition in definitions:
        if not isinstance(definition, dict) or definition.get("type") != "function":
            raise HTTPException(status_code=400, detail="Only function tools are supported.")
        function = definition.get("function")
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            raise HTTPException(status_code=400, detail="Each tool requires a function name.")
        name = function["name"]
        description = function.get("description", "")
        parameters = function.get("parameters", {"type": "object", "properties": {}})
        if not name or name in names or not isinstance(description, str) or not isinstance(parameters, dict):
            raise HTTPException(status_code=400, detail="Invalid or duplicate function tool.")
        names.add(name)

        async def record_call(invocation):
            if not isinstance(invocation.arguments, dict):
                raise ValueError("Copilot returned invalid function arguments.")
            calls.append({
                "id": invocation.tool_call_id or f"call_{uuid4().hex}",
                "type": "function",
                "function": {
                    "name": invocation.tool_name,
                    "arguments": json.dumps(invocation.arguments, ensure_ascii=False),
                },
            })
            return ToolResult(text_result_for_llm="Tool call submitted for client approval.")

        tools.append(Tool(
            name=name,
            description=description,
            parameters=parameters,
            handler=record_call,
            # The handler only returns a proposal; LibreChat approves and executes it.
            skip_permission=True,
            is_terminal=True,
        ))
    return tools


async def _stream_session(client, token: str, instructions: str, conversation: str, tools, calls):
    loop = asyncio.get_running_loop()
    events: asyncio.Queue = asyncio.Queue()

    def on_event(event) -> None:
        if getattr(event, "agent_id", None) is not None:
            return
        event_type = getattr(event.type, "value", event.type)
        if event_type == "assistant.message_delta":
            content = getattr(event.data, "delta_content", None)
            if content:
                loop.call_soon_threadsafe(events.put_nowait, content)

    session = await client.create_session(
        github={"token": token},
        system_message={"content": instructions},
        tools={"definitions": tools, "available_tools": [tool.name for tool in tools]},
        events={"streaming": True},
    )
    async with session:
        session.on(on_event)

        async def send():
            try:
                return await session.send_and_wait(
                    conversation,
                    timeout=COPILOT_TIMEOUT_SECONDS,
                )
            finally:
                loop.call_soon_threadsafe(events.put_nowait, None)

        request = asyncio.create_task(send())
        streamed = False
        try:
            while True:
                delta = await events.get()
                if delta is None:
                    break
                streamed = True
                yield delta
            response = await request
        finally:
            if not request.done():
                request.cancel()
                try:
                    await request
                except asyncio.CancelledError:
                    pass
        content = getattr(getattr(response, "data", None), "content", None)
        if calls:
            yield calls
        elif not isinstance(content, str) or not content:
            raise RuntimeError("Copilot did not return a response.")
        elif not streamed:
            yield content


bearer = HTTPBearer(auto_error=False)


async def require_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> None:
    expected = os.environ.get("COPILOT_ADAPTER_API_KEY", "")
    if (
        not expected
        or credentials is None
        or credentials.scheme.lower() != "bearer"
        or not hmac.compare_digest(credentials.credentials, expected)
    ):
        raise HTTPException(status_code=401, detail="Invalid API key.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.tokens = token_provider_from_environment()
    copilot = _new_copilot_client()
    async with copilot:
        app.state.copilot = copilot
        yield


def _new_copilot_client() -> CopilotClient:
    return CopilotClient(
        mode="empty",
        runtime=RuntimeConnection.for_default(
            base_directory="/tmp/copilot-sdk-runtime",
        ),
        github={"use_logged_in_user": False},
    )


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/models", dependencies=[Depends(require_api_key)])
async def models():
    return {
        "object": "list",
        "data": [{"id": MODEL_ID, "object": "model", "owned_by": "github-copilot"}],
    }


@app.post("/v1/chat/completions", dependencies=[Depends(require_api_key)])
async def chat_completions(body: dict[str, Any]):
    instructions, conversation = parse_messages(body)
    calls: list[dict[str, Any]] = []
    tools = _requested_tools(body, calls)
    token = await app.state.tokens.get()
    copilot = app.state.copilot
    completion_id = f"chatcmpl-{uuid4().hex}"
    created = int(time.time())
    if body.get("stream") is not True:
        parts = []
        async for part in _stream_session(copilot, token, instructions, conversation, tools, calls):
            if isinstance(part, str):
                parts.append(part)
        return _completion("".join(parts) or None, completion_id, created, calls)

    async def stream():
        yield f"data: {json.dumps(_chunk(completion_id, created, {'role': 'assistant'}))}\n\n"
        async for delta in _stream_session(copilot, token, instructions, conversation, tools, calls):
            if isinstance(delta, str):
                payload = {"content": delta}
            else:
                payload = {"tool_calls": [
                    {"index": index, **call} for index, call in enumerate(delta)
                ]}
            yield f"data: {json.dumps(_chunk(completion_id, created, payload))}\n\n"
        yield f"data: {json.dumps(_chunk(completion_id, created, {}, 'tool_calls' if calls else 'stop'))}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
