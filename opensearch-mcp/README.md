# OpenSearch MCP

Exposes an existing OpenSearch cluster to LibreChat as MCP tools. This service does not deploy OpenSearch. You supply the URL and credentials of a cluster you already run.

The server is the official [opensearch-mcp-server-py](https://github.com/opensearch-project/opensearch-mcp-server-py) package, pinned to 0.12.0 in [Dockerfile](./Dockerfile). OpenSearch does not publish a prebuilt image for it, so the compose file builds it locally. The container runs as a non-root user.

It runs in Streamable HTTP mode at `http://opensearch-mcp:9900/mcp` on `opensearch-net`, shared with LibreChat; its port is not published to the host.

## Setup

Run these commands from the project root.

1. If the root `.env` does not already exist, copy the template:

   ```bash
   cp .env.example .env
   ```

   Fill in your cluster details in the root `.env`:

   | Variable | Meaning |
   | --- | --- |
   | `OPENSEARCH_URL` | Cluster API base URL, including any proxy path prefix, for example `https://opensearch.internal/opensearch`. |
   | `OPENSEARCH_AUTH_MODE` | `basic` (default), `token` for a bearer token, or `api_key` for an OpenSearch API key. |
   | `OPENSEARCH_USERNAME` / `OPENSEARCH_PASSWORD` | Cluster credentials for `basic` mode. Use a read-only service account. |
   | `OPENSEARCH_TOKEN` | Bearer token or OpenSearch API key for the selected mode, without the authorization scheme. |
   | `OPENSEARCH_SSL_VERIFY` | `true` to verify the certificate. Set `false` only for a self-signed cluster you trust. |

   For an OpenSearch API key, set `OPENSEARCH_AUTH_MODE=api_key` and `OPENSEARCH_TOKEN` to the key value without the `ApiKey ` prefix. The key ID is not used for authentication. Use `token` mode only for a bearer token. LibreChat forwards the token to the MCP server; API-key mode converts the scheme to `ApiKey` for OpenSearch requests. Scope the key to the required read access. An interactive SAML session is not necessarily a usable API token; confirm the authentication method with your OpenSearch administrator. Tokens are not refreshed automatically. After changing the mode or token, rebuild the MCP image and recreate both LibreChat and the MCP server.

2. Build and start the service:

   ```bash
   podman compose -f compose.yaml -f compose.podman.yaml up -d --build opensearch-mcp
   podman compose -f compose.yaml -f compose.podman.yaml logs opensearch-mcp
   ```

   For Docker, use `docker compose` without the Podman override.

   A cluster that is unreachable shows `Cannot connect to host ...` in the logs. The MCP endpoint still starts, but its tools will fail until the URL is correct.

3. Check the service's MCP health check:

   ```bash
   podman compose -f compose.yaml -f compose.podman.yaml ps opensearch-mcp
   ```

## Connect it to LibreChat

The connection is already configured in [librechat.yaml](../librechat/librechat.yaml):

- Type: MCP (Streamable HTTP)
- URL: `http://opensearch-mcp:9900/mcp`
- The MCP endpoint has no access control. Its port is not published to the host, but containers attached to `opensearch-net` can access it. Token headers supply OpenSearch credentials and do not authenticate access to the MCP endpoint itself.

Select the OpenSearch tools in a LibreChat agent and ask a question about an index. Tool calls require approval.

## Tools and scope

By default the server loads core tools: list indices, get mappings, search, count, cluster health, shard info, msearch, explain, and a generic API tool. Agentic memory and observability tools are off by default. To enable them, add `OPENSEARCH_ENABLED_CATEGORIES` to the root `.env` and pass it through the service's `environment` block in `compose.yaml`. Check the package documentation for the category names.

The generic API tool can call arbitrary OpenSearch REST endpoints. Use a read-only user so that writes are not possible.

## Notes

- LibreChat document search uses the separate RAG API and pgvector service, not this OpenSearch connection.
- The root `.env` holds credentials. Keep it out of version control.
- The values in the root `.env.example` are placeholders. The service will not reach a real cluster until they are replaced.
