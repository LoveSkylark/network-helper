import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "litellm"))

from mcp_policy import has_mcp_tool_activity, is_local_model


class LocalOnlyMcpPolicyTests(unittest.TestCase):
    def test_detects_tools_and_tool_results(self):
        requests = (
            {"tools": [{"type": "function"}]},
            {"tool_choice": "required"},
            {"messages": [{"role": "assistant", "tool_calls": [{"id": "call-1"}]}]},
            {"messages": [{"role": "tool", "content": "private result"}]},
            {"messages": [{"role": "function", "content": "private result"}]},
        )
        for request in requests:
            with self.subTest(request=request):
                self.assertTrue(has_mcp_tool_activity(request))

    def test_plain_chat_does_not_count_as_tool_activity(self):
        self.assertFalse(
            has_mcp_tool_activity({
                "model": "copilot-auto",
                "messages": [{"role": "user", "content": "Hello"}],
            })
        )

    def test_only_configured_local_model_names_are_allowed(self):
        local_names = {"local-ollama", "qwen3-coder:latest"}
        self.assertTrue(is_local_model("local-ollama", local_names))
        self.assertTrue(is_local_model("openai/qwen3-coder:latest", local_names))
        self.assertFalse(is_local_model("copilot-auto", local_names))


if __name__ == "__main__":
    unittest.main()
