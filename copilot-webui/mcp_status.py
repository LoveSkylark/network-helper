import asyncio
import logging
import re
import time
from http import HTTPStatus

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


class MCPToolResultError(Exception):
    def __init__(self, summary, detail=None, *, diagnostics=None):
        super().__init__(detail or summary)
        self.summary = summary
        self.diagnostics = diagnostics or {}


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


def error_diagnostics(result):
    data = result.get("structuredContent")
    diagnostics = {}
    if isinstance(data, dict):
        for field in ("status_code", "http_status"):
            code = str(data.get(field))
            if re.fullmatch(r"[45][0-9]{2}", code):
                diagnostics["http_status"] = int(code)
                break
        diagnostics.update(retry_diagnostics(data.get("retry_after_seconds", data.get("retry_after"))))
        error = data.get("error")
        if isinstance(error, str):
            diagnostics = {**text_diagnostics(error[:1000]), **diagnostics}
    if result.get("isError") and "http_status" not in diagnostics:
        for item in result.get("content", []):
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                diagnostics.update(text_diagnostics(item["text"][:1000]))
                if "http_status" in diagnostics:
                    break
    return diagnostics


def retry_diagnostics(value):
    if type(value) in (str, int) and re.fullmatch(r"[0-9]{1,6}", str(value)):
        return {"retry_after_seconds": int(value)}
    return {}


def text_diagnostics(text):
    match = re.search(r"\b(?:HTTP(?: error)?\s+|status(?: code)?[:= ]+)([45][0-9]{2})\b", text, re.IGNORECASE)
    if match:
        return {"http_status": int(match[1])}
    if re.search(r"\b(?:timed out|timeout|(?:connect|read)timeout)\b", text, re.IGNORECASE):
        return {"upstream_timeout": True}
    return {}


def error_status(result, diagnostics=None):
    data = result.get("structuredContent")
    if diagnostics is None:
        diagnostics = error_diagnostics(result)
    if "http_status" in diagnostics:
        return http_failure(diagnostics["http_status"])
    if diagnostics.get("upstream_timeout"):
        return "the upstream request timed out; check server reachability"
    if result.get("isError"):
        return "the MCP server reported a tool error"
    if isinstance(data, dict) and (data.get("error") or data.get("status") == "error" or data.get("success") is False):
        return "the MCP server reported a tool error"
    return None


def http_failure(code):
    if code == 401:
        return "authentication failed (HTTP 401); check the configured credentials"
    if code == 403:
        return "access denied (HTTP 403); check token expiry and permissions"
    if code == 404:
        return "the requested endpoint or resource was not found (HTTP 404); this is not a successful search"
    try:
        return f"HTTP {code} {HTTPStatus(code).phrase}"
    except ValueError:
        return f"HTTP {code}"


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
