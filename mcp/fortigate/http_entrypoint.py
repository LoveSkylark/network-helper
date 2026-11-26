"""Expose FortiOS tools through a compact, searchable MCP catalog."""

import os

from fastmcp.server import create_proxy
from fastmcp.server.transforms.search import BM25SearchTransform
from server import mcp as upstream

mcp = create_proxy(
    upstream,
    name="FortiOS MCP Server",
    instructions=(
        "Use the generic CMDB, monitor, and log tools for FortiOS retrieval, "
        "or search for a specific operation and call it by name."
    ),
)
mcp.add_transform(
    BM25SearchTransform(
        always_visible=["cmdb_list", "cmdb_get", "monitor_get", "log_get"]
    )
)


def main() -> None:
    if os.environ.get("MCP_TRANSPORT", "stdio") == "streamable-http":
        mcp.run(
            transport="http",
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8000")),
        )
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
