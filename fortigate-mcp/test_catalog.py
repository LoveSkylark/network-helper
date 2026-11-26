import os
import unittest
from unittest.mock import AsyncMock, patch

from fastmcp import Client

import http_entrypoint


class FortiOSCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_and_call_named_vdom_tool(self):
        env = {"FORTIOS_HOST": "https://fortios.invalid", "FORTIOS_API_TOKEN": "test"}
        with patch.dict(os.environ, env), patch(
            "fortios_client.FortiOSClient.cmdb_get",
            new_callable=AsyncMock,
            return_value={"results": []},
        ) as cmdb_get:
            async with Client(http_entrypoint.mcp) as client:
                names = {tool.name for tool in await client.list_tools()}
                self.assertEqual(
                    names,
                    {
                        "cmdb_list",
                        "cmdb_get",
                        "monitor_get",
                        "log_get",
                        "search_tools",
                        "call_tool",
                    },
                )

                search = await client.call_tool("search_tools", {"query": "list VDOMs"})
                self.assertIn("system_vdom_list", str(search.content))

                result = await client.call_tool(
                    "call_tool",
                    {"name": "system_vdom_list", "arguments": {"vdom": "example"}},
                )
                self.assertFalse(result.is_error)
                cmdb_get.assert_awaited_once_with("system/vdom", vdom="example")

                result = await client.call_tool(
                    "cmdb_list",
                    {"resource_path": "firewall/policy", "vdom": "another"},
                )
                self.assertFalse(result.is_error)
                cmdb_get.assert_any_await("firewall/policy", None, vdom="another")


if __name__ == "__main__":
    unittest.main()
