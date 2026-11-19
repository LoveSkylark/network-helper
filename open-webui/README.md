# Open WebUI

Chat front end for the cluster. It runs from the root [compose.yaml](../compose.yaml) and publishes port 5000 on all interfaces.

## Setup

Run these commands from the project root. Copy the template only if the root `.env` does not already exist:

```bash
cp .env.example .env
```

Edit the root `.env` and set `WEBUI_URL` to the URL users will access, without a trailing slash. Set `WEBUI_SECRET_KEY` (generate with `openssl rand -hex 32`) and the other values described in the [root README](../README.md). Then start the cluster:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f
```

For Podman, use `podman compose -f compose.yaml -f compose.podman.yaml` instead of `docker compose` in these commands.

Chat history and accounts are stored in the named volume `open-webui-data`. Remove it with `docker compose down -v` only if you want to reset Open WebUI.

## Microsoft sign-in

Sign-in uses Microsoft Entra ID (OAuth/OIDC). Non-secret settings live in `compose.yaml`; the client ID, client secret, and tenant ID live in the root `.env`.

1. In the Entra admin center, register an application (Web platform).
2. Add the redirect URI `<WEBUI_URL>/oauth/microsoft/callback`, replacing `<WEBUI_URL>` with its value from the root `.env`.
3. Create a client secret and copy its value.
4. Fill `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, and `MICROSOFT_CLIENT_TENANT_ID` in the root `.env`.
5. Restart: `docker compose up -d`.

`ENABLE_OAUTH_SIGNUP=true` lets first-time Microsoft users create accounts. Set it to `false` to allow only existing users.

## Layout

- `compose.yaml` (repo root): cluster definition. Open WebUI joins a dedicated network for each MCP service so it can reach each by service name.
- `.env` (repo root): local secrets used by Compose. Not committed; keep it out of version control.

## Connect the FortiOS MCP server

The FortiOS server runs in the same cluster as `fortios-mcp` and listens on `http://fortios-mcp:8000/mcp` (FastMCP's default path) on `fortios-net`.

The connection is seeded automatically. The `TOOL_SERVER_CONNECTIONS` env var in `compose.yaml` is read on first boot and stored in Open WebUI's database (`tool_server.connections`). Verified on a fresh volume: the connection appeared with no manual step, and the admin API returned it.

- Type: MCP (Streamable HTTP), URL `http://fortios-mcp:8000/mcp`, Auth none.
- The server has no authentication. Its port is not published to the host; containers attached to `fortios-net` can access it.
- To change the connection later, edit it in **Settings > Admin > Integrations**, or post it to `POST /api/v1/configs/tool_servers` with an admin token. Whether a later env change overrides a UI edit is not verified.

The FortiOS tools can create, update, and delete firewall objects and policies. Restrict who can use this connection, and consider a read-only FortiOS API token while you test.

## Connect the OpenSearch MCP server

The OpenSearch MCP service is described in [opensearch-mcp/README.md](../opensearch-mcp/README.md). It is listed in `TOOL_SERVER_CONNECTIONS` at `http://opensearch-mcp:9900/mcp`, but that env var is only read on first boot of an empty volume. For an existing volume, add it in the GUI or through the admin API, as described there.

## GitHub Models

Compose configures GitHub Models at `https://models.github.ai/inference` as an OpenAI-compatible backend, using `GITHUB_TOKEN` from the root `.env`. Supply a token with access to the models you intend to use.
