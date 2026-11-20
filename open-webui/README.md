# Open WebUI

Chat front end for the cluster. It runs from the root [compose.yaml](../compose.yaml) and publishes port 80 on all interfaces.

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

## MCP tool status and authentication

The custom image shows when a tool starts, finishes, or fails for all six bundled MCP servers. It also forwards informational text and progress when the server sends them (for example, `LibreNMS: Listing devices...`). It does not forward log metadata or change tool approval. After changing the forwarding patch, rebuild and recreate Open WebUI with `docker compose up -d --no-deps --build open-webui`.

FortiOS, LibreNMS, and NetBox send API tokens per request. OpenSearch and Cisco ISE API calls use configured credentials. Rotate expired or revoked credentials and recreate the affected container. Cisco ACI acquires a new cookie on demand after APIC reports token expiry; only a rejected GET is retried once. Cisco ISE web-session tools handle their own cookie expiry. No service sends background requests solely to keep a login alive, and existing request timeouts still apply.

## GitHub Copilot

The custom image includes the Copilot SDK and its Open WebUI Pipe. Set `COPILOT_GITHUB_TOKEN` in the root `.env` to a personal fine-grained token with the **Copilot Requests** account permission and access to Copilot. All users of this Pipe share that account and its usage limits.

After starting the cluster, an Open WebUI administrator must register the Pipe:

1. Open **Admin Panel > Functions** and create a function with ID `copilot`.
2. Set its content to `from copilot_pipe import Pipe`, save it, and enable it.
3. In a new chat, select a **Copilot:** model and select the MCP servers to use.

The Pipe uses only the selected MCP tools and asks for confirmation before every tool call. A call without an interactive confirmation is denied. MCP tools can modify network devices, so restrict model and tool access to authorized users. Chat messages and approved tool results are sent to GitHub Copilot under the shared account. The Pipe supports text messages; images are not supported.

Existing Open WebUI volumes may retain the retired GitHub Models connection. Remove it under **Admin Settings > Connections**.
