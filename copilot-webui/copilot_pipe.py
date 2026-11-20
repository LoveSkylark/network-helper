"""
title: GitHub Copilot
description: Copilot SDK chat with selected Open WebUI MCP tools.
version: 1.0.0
"""

import asyncio
import json
import os
import tempfile

from copilot import CopilotClient, RuntimeConnection, ToolSet
from copilot.tools import Tool, ToolResult


COPILOT_SESSION_TIMEOUT_SECONDS = 600


def _client(state_directory):
    if not os.environ.get("COPILOT_GITHUB_TOKEN"):
        raise RuntimeError("COPILOT_GITHUB_TOKEN is not configured.")
    return CopilotClient(
        mode="empty",
        runtime=RuntimeConnection.for_default(base_directory=state_directory),
    )


def _messages(body):
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("The chat request does not contain any messages.")

    system_messages = []
    conversation = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if isinstance(content, list):
            if any(part.get("type") != "text" for part in content):
                raise ValueError("This Copilot integration supports text messages only.")
            content = "\n".join(part.get("text", "") for part in content)
        if content is not None and not isinstance(content, str):
            raise ValueError("Unsupported chat message content.")
        if role == "system":
            system_messages.append(content or "")
        elif role in ("user", "assistant", "tool"):
            conversation.append({"role": role, "content": content})
        else:
            raise ValueError(f"Unsupported chat message role: {role}")

    if not any(message["role"] == "user" for message in conversation):
        raise ValueError("The chat request does not contain a user message.")
    return "\n\n".join(system_messages), json.dumps(conversation, ensure_ascii=False)


def _make_tool(name, entry, event_call):
    spec = entry["spec"]
    invoke = entry["callable"]

    async def handler(invocation):
        arguments = invocation.arguments
        if not isinstance(arguments, dict):
            return ToolResult(
                result_type="failure",
                text_result_for_llm="Tool arguments must be a JSON object.",
            )
        if event_call is None:
            return ToolResult(
                result_type="denied",
                text_result_for_llm="Tool calls require an interactive confirmation.",
            )
        try:
            confirmed = await asyncio.wait_for(
                event_call({
                    "type": "confirmation",
                    "data": {
                        "title": f"Allow tool: {name}?",
                        "message": json.dumps(arguments, ensure_ascii=False, indent=2),
                    },
                }),
                timeout=120,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                result_type="timeout",
                text_result_for_llm="Tool confirmation timed out.",
            )
        if confirmed is not True:
            return ToolResult(
                result_type="denied",
                text_result_for_llm="Tool call was not approved.",
            )
        result = await invoke(**arguments)
        return ToolResult(text_result_for_llm=json.dumps(result, ensure_ascii=False, default=str))

    return Tool(
        name=name,
        description=spec.get("description", ""),
        parameters=spec.get("parameters"),
        handler=handler,
        skip_permission=True,
    )


async def _stream_response(session, conversation):
    loop = asyncio.get_running_loop()
    events = asyncio.Queue()

    def on_event(event):
        if getattr(event, "agent_id", None) is not None:
            return

        event_type = getattr(event.type, "value", event.type)
        if event_type == "assistant.message_delta":
            content = getattr(event.data, "delta_content", None)
            if content:
                loop.call_soon_threadsafe(events.put_nowait, ("delta", content))
        elif event_type == "tool.execution_start":
            loop.call_soon_threadsafe(events.put_nowait, ("status", "Copilot is running a tool..."))
        elif event_type == "tool.execution_complete":
            loop.call_soon_threadsafe(events.put_nowait, ("status", "Copilot is preparing its response..."))

    session.on(on_event)

    async def send():
        try:
            return await session.send_and_wait(
                conversation,
                timeout=COPILOT_SESSION_TIMEOUT_SECONDS,
            )
        finally:
            loop.call_soon_threadsafe(events.put_nowait, None)

    request = asyncio.create_task(send())
    streamed = False
    try:
        while True:
            item = await events.get()
            if item is None:
                break
            kind, content = item
            if kind == "delta":
                streamed = True
                yield content
            else:
                yield {"status": content}

        response = await request
        if response is None or not response.data.content:
            raise RuntimeError("Copilot did not return a response.")
        if not streamed:
            yield response.data.content
    finally:
        if not request.done():
            request.cancel()
            try:
                await request
            except asyncio.CancelledError:
                pass


class Pipe:
    async def pipes(self):
        with tempfile.TemporaryDirectory(prefix="copilot-models-") as state:
            async with _client(state) as client:
                models = await client.list_models()
        return [{"id": model.id, "name": f"Copilot: {model.name}"} for model in models]

    async def pipe(
        self,
        body: dict,
        __tools__: dict = None,
        __event_call__=None,
        __event_emitter__=None,
    ):
        system, conversation = _messages(body)
        model = body["model"].split(".", 1)[-1]
        selected_tools = {
            name: entry
            for name, entry in (__tools__ or {}).items()
            if entry.get("type") == "mcp"
        }
        definitions = [
            _make_tool(name, entry, __event_call__)
            for name, entry in selected_tools.items()
        ]
        allowed = ToolSet()
        for name in selected_tools:
            allowed.add_custom(name)

        instructions = (
            "The user message contains the conversation as a JSON array. "
            "Use the role labels to interpret the conversation and respond to the "
            "latest user message."
        )
        if system:
            instructions += "\n\n" + system

        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": "Connecting to Copilot...", "done": False},
            })

        with tempfile.TemporaryDirectory(prefix="copilot-chat-") as state:
            async with _client(state) as client:
                async with await client.create_session(
                    model=model,
                    system_message={"content": instructions},
                    tools={"definitions": definitions, "available_tools": allowed},
                    events={"streaming": True},
                ) as session:
                    if __event_emitter__:
                        await __event_emitter__({
                            "type": "status",
                            "data": {"description": "Waiting for Copilot...", "done": False},
                        })
                    try:
                        async for item in _stream_response(session, conversation):
                            if isinstance(item, dict):
                                if __event_emitter__:
                                    await __event_emitter__({
                                        "type": "status",
                                        "data": {
                                            "description": item["status"],
                                            "done": False,
                                        },
                                    })
                            else:
                                yield item
                    except asyncio.TimeoutError:
                        if __event_emitter__:
                            await __event_emitter__({
                                "type": "status",
                                "data": {
                                    "description": (
                                        f"Copilot timed out after "
                                        f"{COPILOT_SESSION_TIMEOUT_SECONDS} seconds."
                                    ),
                                    "done": True,
                                },
                            })
                        raise
                    except Exception:
                        if __event_emitter__:
                            await __event_emitter__({
                                "type": "status",
                                "data": {"description": "Copilot request failed.", "done": True},
                            })
                        raise
                    else:
                        if __event_emitter__:
                            await __event_emitter__({
                                "type": "status",
                                "data": {"description": "Response complete.", "done": True},
                            })
