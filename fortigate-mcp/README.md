# FortiOS MCP

Runs the FortiOS MCP server in a container for the cluster. The source is not stored in this repo. The Dockerfile clones the upstream project [paoloamato2/fortinet-mcp-server](https://github.com/paoloamato2/fortinet-mcp-server) at a pinned commit and installs its locked dependencies with `uv`. The [OpenSearch MCP](../opensearch-mcp/README.md) build pins its package version.

The server listens at `http://fortios-mcp:8000/mcp` on `fortios-net`, shared with Open WebUI; its port is not published to the host.

## Setup

Run these commands from the project root.

1. If the root `.env` does not already exist, copy the template:

   ```bash
   cp .env.example .env
   ```

   Set `FORTIOS_HOST`, `FORTIOS_API_TOKEN` (create it under System > Administrators > REST API Admin), and `FORTIOS_VERIFY_SSL`. A read-only API profile is a good choice while testing.

2. Start it through the root compose file, which builds the image:

   ```bash
   podman compose -f compose.yaml -f compose.podman.yaml up -d --build fortios-mcp
   ```

   If the container keeps the old image, use `podman compose -f compose.yaml -f compose.podman.yaml up -d --force-recreate fortios-mcp`.

## Updating the upstream version

The pinned commit is the `UPSTREAM_REF` build argument in [Dockerfile](./Dockerfile). To move to a newer commit, change that value and rebuild.

## Notes

- The FortiOS tools can create, update, and delete firewall objects and policies. Restrict who can use the connection.
- The root `.env` holds the API token and is excluded by the root `.gitignore`.
- Open WebUI connects to this server through `TOOL_SERVER_CONNECTIONS` in the root [compose.yaml](../compose.yaml).
