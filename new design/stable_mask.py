"""
stable_mask.py - global, stable placeholders for LiteLLM (HMAC + Redis).

The same real value always becomes the same placeholder, in every chat and for
every user, e.g. 10.0.4.22 -> <IP_7f3a9c21d0>. Real values never leave the
gateway. A Redis hash maps placeholder -> real value so replies, streamed
replies and tool-call arguments can be translated back.

Environment:
  STABLEMASK_HMAC_KEY   required, long random secret (e.g. `openssl rand -hex 32`).
                        Changing it changes every placeholder.
  STABLEMASK_REDIS_URL  default redis://redis:6379/0
"""
import hashlib
import hmac
import ipaddress
import os
import re
from typing import Any, AsyncGenerator, Callable, Optional

import redis.asyncio as redis
from litellm.integrations.custom_guardrail import CustomGuardrail
from litellm.types.utils import ChatCompletionDeltaToolCall, Function

MAP_KEY = "stablemask:map"     # Redis hash: placeholder -> real value
TOKEN_HEX = (10, 16, 64)       # placeholder length; longer only on a collision


# ---------------------------------------------------------------------------
# What to mask. Each entry: KIND -> (regex, normalize). normalize returns the
# canonical value to hash, or None to skip a false match.
# ---------------------------------------------------------------------------
def _ip(value: str) -> Optional[str]:
    try:
        return str(ipaddress.ip_address(value))   # canonical form, validates
    except ValueError:
        return None


PATTERNS: dict[str, tuple[re.Pattern, Callable[[str], Optional[str]]]] = {
    "IP": (
        re.compile(
            r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\.?\d)"                  # IPv4
            r"|(?<![:\w])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![:\w])"  # IPv6
        ),
        _ip,
    ),
    # Example: internal hostnames. Adjust the domain, then uncomment.
    # "HOST": (re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.corp\.example\.com\b", re.I),
    #          lambda v: v.lower()),
}

TOKEN_RE = re.compile(r"<([A-Z]+)_([0-9a-f]{10,64})>")
PARTIAL_TOKEN_RE = re.compile(r"<[A-Z]*(?:_[0-9a-f]{0,64})?$")   # cut-off token at chunk end


class StableMask(CustomGuardrail):
    def __init__(self, **kwargs: Any) -> None:
        self.secret = os.environ["STABLEMASK_HMAC_KEY"].encode()
        self.store = redis.from_url(
            os.environ.get("STABLEMASK_REDIS_URL", "redis://redis:6379/0"),
            decode_responses=True,
        )
        self._cache: dict[str, str] = {}   # local copy of known placeholders
        super().__init__(**kwargs)

    # ---------------- placeholders ----------------
    async def _token_for(self, kind: str, value: str) -> str:
        digest = hmac.new(self.secret, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()
        for n in TOKEN_HEX:
            token = f"<{kind}_{digest[:n]}>"
            if self._cache.get(token) == value:
                return token
            if await self.store.hsetnx(MAP_KEY, token, value):   # first time seen
                self._cache[token] = value
                return token
            if await self.store.hget(MAP_KEY, token) == value:   # seen before
                self._cache[token] = value
                return token
            # different value already owns this short token: try a longer one
        raise RuntimeError("stable_mask: placeholder collision at full length")

    async def mask(self, text: str) -> str:
        for kind, (regex, normalize) in PATTERNS.items():
            out, last = [], 0
            for m in regex.finditer(text):
                value = normalize(m.group(0))
                if value is None:
                    continue
                out.append(text[last:m.start()])
                out.append(await self._token_for(kind, value))
                last = m.end()
            out.append(text[last:])
            text = "".join(out)
        return text

    async def restore(self, text: str) -> str:
        out, last = [], 0
        for m in TOKEN_RE.finditer(text):
            token = m.group(0)
            value = self._cache.get(token) or await self.store.hget(MAP_KEY, token)
            if value is None:
                continue              # not ours: leave it as the model wrote it
            self._cache[token] = value
            out.append(text[last:m.start()])
            out.append(value)
            last = m.end()
        out.append(text[last:])
        return "".join(out)

    # ---------------- request: mask everything sent to the model ----------------
    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        for msg in data.get("messages") or []:
            content = msg.get("content")
            if isinstance(content, str):
                msg["content"] = await self.mask(content)
            elif isinstance(content, list):          # multi-part messages
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        part["text"] = await self.mask(part["text"])
            for call in msg.get("tool_calls") or []:  # earlier tool calls in history
                fn = call.get("function") or {}
                if isinstance(fn.get("arguments"), str):
                    fn["arguments"] = await self.mask(fn["arguments"])
        return data

    # ---------------- response: restore real values ----------------
    async def async_post_call_success_hook(self, data: dict, user_api_key_dict, response):
        for choice in getattr(response, "choices", None) or []:
            message = getattr(choice, "message", None)
            if message is None:
                continue
            if isinstance(message.content, str):
                message.content = await self.restore(message.content)
            for call in getattr(message, "tool_calls", None) or []:
                if call.function and isinstance(call.function.arguments, str):
                    call.function.arguments = await self.restore(call.function.arguments)
        return response

    async def async_post_call_streaming_iterator_hook(
        self, user_api_key_dict, response, request_data: dict
    ) -> AsyncGenerator[Any, None]:
        held: dict[tuple, str] = {}   # text held back because it may be half a placeholder

        async def feed(key: tuple, text: str, final: bool) -> str:
            buf = held.pop(key, "") + (text or "")
            if not final:
                m = PARTIAL_TOKEN_RE.search(buf)
                if m:
                    held[key] = buf[m.start():]
                    buf = buf[:m.start()]
            return await self.restore(buf)

        async for chunk in response:
            for choice in getattr(chunk, "choices", None) or []:
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue
                final = getattr(choice, "finish_reason", None) is not None
                idx = getattr(choice, "index", 0)
                if delta.content is not None or (final and (idx, "c") in held):
                    delta.content = await feed((idx, "c"), delta.content, final)
                for call in getattr(delta, "tool_calls", None) or []:
                    if call.function and call.function.arguments is not None:
                        call.function.arguments = await feed(
                            (idx, "t", call.index), call.function.arguments, final
                        )
                if final:   # flush whatever is still held for this choice
                    for key in [k for k in held if k[0] == idx]:
                        rest = await feed(key, "", True)
                        if not rest:
                            continue
                        if key[1] == "c":
                            delta.content = (delta.content or "") + rest
                        else:   # tail of a tool call's arguments
                            delta.tool_calls = (delta.tool_calls or []) + [
                                ChatCompletionDeltaToolCall(
                                    index=key[2], type="function",
                                    function=Function(arguments=rest),
                                )
                            ]
            yield chunk