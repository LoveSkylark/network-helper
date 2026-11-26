import os

from fastapi import HTTPException
from litellm.integrations.custom_guardrail import CustomGuardrail

from mcp_policy import has_mcp_tool_activity, is_local_model


class LocalOnlyMcpGuardrail(CustomGuardrail):
    async def async_pre_call_hook(
        self,
        user_api_key_dict,
        cache,
        data: dict,
        call_type,
    ):
        model_names = {
            os.getenv("LOCAL_MODEL_NAME", "local-ollama"),
            os.getenv("OLLAMA_MODEL", ""),
        }
        if is_local_model(data.get("model"), model_names):
            return data
        if (
            os.getenv("ALLOW_COPILOT_MCP", "false").lower() == "true"
            and data.get("model") in {"copilot-auto", "openai/copilot-auto"}
        ):
            return data
        if has_mcp_tool_activity(data):
            raise HTTPException(
                status_code=403,
                detail="MCP tools and results require a local model or approved Copilot access.",
            )
        return data
