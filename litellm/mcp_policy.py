from collections.abc import Mapping
from typing import Any


def has_mcp_tool_activity(request_data: Mapping[str, Any]) -> bool:
    if request_data.get("tools") or request_data.get("functions"):
        return True
    if request_data.get("tool_choice") not in (None, "none"):
        return True
    for message in request_data.get("messages") or []:
        if not isinstance(message, Mapping):
            continue
        if message.get("role") in ("tool", "function"):
            return True
        if message.get("tool_calls") or message.get("function_call"):
            return True
    return False


def is_local_model(model: Any, local_model_names: set[str]) -> bool:
    if not isinstance(model, str):
        return False
    return any(model == name or model.endswith(f"/{name}") for name in local_model_names if name)
