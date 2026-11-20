import asyncio
import logging
import re
import time

import httpx2
from mcp.shared.exceptions import MCPError
from mcp_types import REQUEST_TIMEOUT


log = logging.getLogger(__name__)
SERVER_NAMES = {
    "cisco-aci-mcp": "Cisco ACI",
    "cisco-ise-mcp": "Cisco ISE",
    "fortios-mcp": "FortiOS",
    "librenms-mcp": "LibreNMS",
    "netbox-mcp": "NetBox",
    "opensearch-mcp": "OpenSearch",
}


async def emit_status(emitter, server, message, *, done=False, error=False):
    if emitter is None or server not in SERVER_NAMES:
        return
    try:
        await emitter({
            "type": "status",
            "data": {
                "action": "mcp_tool",
                "description": f"{SERVER_NAMES[server]}: {message}",
                "done": done,
                "error": error,
            },
        })
    except Exception:
        log.warning("Could not send status for MCP server %s", server, exc_info=True)


def status_text(value):
    return " ".join(value[:300].split()) if isinstance(value, str) else ""


def error_status(result):
    data = result.get("structuredContent")
    if isinstance(data, dict):
        error = data.get("error")
        status = data.get("status")
        if error or status == "error" or data.get("success") is False:
            code = data.get("status_code", data.get("http_status"))
            if code in (401, 403, "401", "403"):
                return http_failure(code)
            return reported_failure(error if isinstance(error, str) else "")
    if result.get("isError"):
        text = " ".join(
            item["text"][:1000]
            for item in result.get("content", [])
            if item.get("type") == "text" and isinstance(item.get("text"), str)
        )
        return reported_failure(text)
    return None


def reported_failure(text):
    match = re.search(r"\b(?:HTTP(?: error)?\s+|status(?: code)?[:= ]+)(401|403)\b", text, re.IGNORECASE)
    if match:
        return http_failure(match[1])
    if re.search(r"\b(?:timed out|timeout|(?:connect|read)timeout)\b", text, re.IGNORECASE):
        return "the upstream request timed out; check server reachability"
    return "the MCP server reported a tool error"


def http_failure(code):
    if code in (401, "401"):
        return "authentication failed (HTTP 401); check the configured credentials"
    if code in (403, "403"):
        return "access denied (HTTP 403); check token expiry and permissions"
    return "the MCP server reported a tool error"


async def call_with_status(emitter, server, tool, call):
    start = time.monotonic()
    await emit_status(emitter, server, f"Running {tool}...")

    async def progress(value, total, message):
        detail = status_text(message)
        if not detail:
            detail = f"{value:g} of {total:g}" if total is not None else f"progress {value:g}"
        await emit_status(emitter, server, f"{tool}: {detail}")

    async def report_wait():
        while True:
            await asyncio.sleep(10)
            await emit_status(emitter, server, f"Still running {tool} ({time.monotonic() - start:.0f}s)...")

    try:
        waiting = asyncio.create_task(report_wait())
        try:
            result = await call(progress)
        finally:
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)
    except (TimeoutError, httpx2.TimeoutException):
        await emit_status(emitter, server, f"{tool} timed out; it was not retried.", done=True, error=True)
        raise
    except httpx2.HTTPStatusError as exc:
        await emit_status(emitter, server, f"{tool}: {http_failure(exc.response.status_code)}.", done=True, error=True)
        raise
    except MCPError as exc:
        detail = "timed out" if exc.code == REQUEST_TIMEOUT else "failed"
        await emit_status(emitter, server, f"{tool} {detail}; it was not retried.", done=True, error=True)
        raise
    except Exception:
        await emit_status(emitter, server, f"{tool} failed; it was not retried.", done=True, error=True)
        raise

    elapsed = time.monotonic() - start
    failure = error_status(result)
    if failure:
        await emit_status(emitter, server, f"{tool}: {failure} ({elapsed:.1f}s).", done=True, error=True)
    else:
        await emit_status(emitter, server, f"{tool} completed in {elapsed:.1f}s.", done=True)
    return result
