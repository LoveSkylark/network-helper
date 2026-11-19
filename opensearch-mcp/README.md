# OpenSearch MCP

Exposes an existing OpenSearch cluster to Open WebUI as MCP tools. This service does not deploy OpenSearch. You supply the URL and credentials of a cluster you already run.

The server is the official [opensearch-mcp-server-py](https://github.com/opensearch-project/opensearch-mcp-server-py) package, pinned to 0.12.0 in [Dockerfile](./Dockerfile). OpenSearch does not publish a prebuilt image for it, so the compose file builds it locally. The container runs as a non-root user.

It runs in Streamable HTTP mode at `http://opensearch-mcp:9900/mcp` on `opensearch-net`, shared with Open WebUI; its port is not published to the host.

## Setup

Run these commands from the project root.

1. If the root `.env` does not already exist, copy the template:

   ```bash
   cp .env.example .env
   ```

   Fill in your cluster details in the root `.env`:

   | Variable | Meaning |
   | --- | --- |
   | `OPENSEARCH_URL` | Cluster endpoint, for example `https://opensearch.internal:9200` |
   | `OPENSEARCH_USERNAME` / `OPENSEARCH_PASSWORD` | Cluster credentials. Use a read-only user while testing. |
   | `OPENSEARCH_SSL_VERIFY` | `true` to verify the certificate. Set `false` only for a self-signed cluster you trust. |

2. Build and start the service:

   ```bash
   podman compose -f compose.yaml -f compose.podman.yaml up -d --build opensearch-mcp
   podman compose -f compose.yaml -f compose.podman.yaml logs opensearch-mcp
   ```

   For Docker, use `docker compose` without the Podman override.

   A cluster that is unreachable shows `Cannot connect to host ...` in the logs. The MCP endpoint still starts, but its tools will fail until the URL is correct.

3. Check the MCP endpoint from the Open WebUI container. The following command prints the HTTP status of an MCP initialize request:

   ```bash
   podman exec -i open-webui python -c "import urllib.request,json; r=urllib.request.Request('http://opensearch-mcp:9900/mcp', data=json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'check','version':'0'}}}).encode(), headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'}); print(urllib.request.urlopen(r, timeout=20).status)"
   ```

## Connect it to Open WebUI

The compose file already lists the connection in `TOOL_SERVER_CONNECTIONS`:

- Type: MCP (Streamable HTTP)
- URL: `http://opensearch-mcp:9900/mcp`
- Auth: none. The server has no authentication. Its port is not published to the host, but containers attached to `opensearch-net` can access it.

That variable is read only on first boot of an empty `open-webui-data` volume. If Open WebUI already has a volume, add the connection by one of these routes:

- **GUI:** sign in as an admin, open **Settings > Admin > Integrations**, add an MCP connection with the URL above, and save.
- **Admin API:** post the full list to `POST /api/v1/configs/tool_servers` with an admin bearer token. The body is `{"TOOL_SERVER_CONNECTIONS": [...]}`. Include every existing connection, such as FortiOS, or the request replaces them.

Then open a chat, enable the OpenSearch tools for the model, and ask a question about an index.

## Tools and scope

By default the server loads core tools: list indices, get mappings, search, count, cluster health, shard info, msearch, explain, and a generic API tool. Agentic memory and observability tools are off by default. To enable them, add `OPENSEARCH_ENABLED_CATEGORIES` to the root `.env` and pass it through the service's `environment` block in `compose.yaml`. Check the package documentation for the category names.

The generic API tool can call arbitrary OpenSearch REST endpoints. Use a read-only user so that writes are not possible.

## Notes

- Do not confuse this with OpenSearch as a vector store for RAG. That is a separate Open WebUI setting (`VECTOR_DB=opensearch`) and does not give chats access to your indices.
- The root `.env` holds credentials. Keep it out of version control.
- The values in the root `.env.example` are placeholders. The service will not reach a real cluster until they are replaced.
