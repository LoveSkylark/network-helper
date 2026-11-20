"""Serve the upstream ACI FastMCP instance over Streamable HTTP.

Upstream scripts/server.py only runs stdio (mcp.run() with no transport).
Importing its module-level `mcp` object and running it here keeps upstream code unchanged.
"""

import os

from aci_auth import install_token_refresh
from server import aci_client, mcp

install_token_refresh(aci_client)

mcp.run(
    transport="streamable-http",
    host=os.getenv("MCP_HOST", "0.0.0.0"),
    port=int(os.getenv("MCP_PORT", "8000")),
)
