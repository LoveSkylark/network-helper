import unittest
from unittest.mock import patch

from fastmcp import Client, FastMCP

with patch.object(FastMCP, "run"):
    import http_entrypoint


class ACICatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_and_call_reach_underlying_tools(self):
        async with Client(http_entrypoint.mcp) as client:
            names = {tool.name for tool in await client.list_tools()}
            self.assertEqual(names, {"search_tools", "call_tool"})

            search = await client.call_tool("search_tools", {"query": "tenants"})
            self.assertIn("aci_tenants_get", str(search.content))

            result = await client.call_tool(
                "call_tool", {"name": "aci_simple_test", "arguments": {}}
            )
            self.assertFalse(result.is_error)
            self.assertIn("success", str(result.content))


if __name__ == "__main__":
    unittest.main()
