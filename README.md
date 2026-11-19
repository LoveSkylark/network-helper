# MCP cluster

Open WebUI is the front end, with several MCP services behind it. Compose configures GitHub Models as the OpenAI-compatible AI backend, and Open WebUI uses the MCP services as tools. Everything starts from one compose file in this folder.

## Services

| Service | Folder | Host port | Container port | Purpose |
|---|---|---|---|---|
| open-webui | `open-webui/` (image only) | 5100 | 8080 | Chat UI and Microsoft sign-in |
| fortios-mcp | `fortigate-mcp/` | 5101 | 8000 | FortiGate / FortiOS tools |
| opensearch-mcp | `opensearch-mcp/` | 5102 | 9900 | OpenSearch tools |
| cisco-ise-mcp | `cisco-ise-mcp/` | 5103 | 5000 | Cisco ISE tools |
| cisco-aci-mcp | `cisco-aci-mcp/` | 5104 | 8000 | Cisco ACI tools |
| netbox-mcp | `netbox-mcp/` | 5105 | 8000 | NetBox tools (read-only) |
| librenms-mcp | `librenms-mcp/` | 5106 | 8000 | LibreNMS tools (read-only by default) |

The LibreNMS MCP exits at startup until `LIBRENMS_TOKEN` is set in `.env`. Its `READ_ONLY_MODE` is `true` in compose, so it can't make write calls.

All host ports bind to `127.0.0.1` and are in the 5100+ range. Port 5000 is avoided because macOS AirPlay Receiver holds it.

Services talk to each other on the `mcp-net` network by service name (for example `http://fortios-mcp:8000/mcp`). Open WebUI's `TOOL_SERVER_CONNECTIONS` in [compose.yaml](./compose.yaml) lists these MCP endpoints.

## Layout

```
compose.yaml          Cluster definition (the only compose file)
.env                  All configuration and secrets for every container
open-webui/           Open WebUI deployment notes
fortigate-mcp/        FortiOS MCP build (pinned upstream)
opensearch-mcp/       OpenSearch MCP build (pinned PyPI package)
cisco-ise-mcp/        Cisco ISE MCP build (pinned upstream)
cisco-aci-mcp/        Cisco ACI MCP build (pinned upstream + HTTP wrapper)
netbox-mcp/           NetBox MCP build (pinned upstream, read-only)
librenms-mcp/         LibreNMS MCP build (pinned upstream, read-only by default)
```

## Configuration

From the project root, copy the template if you do not already have a root `.env`:

```sh
cp .env.example .env
```

Set the values for the integrations you use. Compose reads this root `.env` for variable substitution; service-local `.env` files are not loaded by the cluster compose file. The root `.gitignore` excludes `.env`; do not commit it.

Things to set before first use:

- **Open WebUI:** `WEBUI_SECRET_KEY` (generate with `openssl rand -hex 32`), the local admin (`WEBUI_ADMIN_*`), and the Microsoft Entra values (`MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_CLIENT_TENANT_ID`).
- **GitHub Models:** `GITHUB_TOKEN`.
- **FortiOS:** `FORTIOS_HOST`, `FORTIOS_API_TOKEN`, `FORTIOS_VDOM`, `FORTIOS_VERIFY_SSL`.
- **OpenSearch:** `OPENSEARCH_URL`, `OPENSEARCH_USERNAME`, `OPENSEARCH_PASSWORD`, `OPENSEARCH_SSL_VERIFY`.
- **Cisco ISE:** `ISE_IP`, `API_USERNAME`, `API_PWD`, certificate verification flags.
- **Cisco ACI:** `APIC_URL`, `ACI_USERNAME`, `ACI_PASSWORD`. These map to the `USERNAME` and `PASSWORD` variables the upstream server reads.
- **NetBox:** `NETBOX_URL`, `NETBOX_TOKEN`, `NETBOX_VERIFY_SSL`.
- **LibreNMS:** `LIBRENMS_URL`, `LIBRENMS_TOKEN`, `LIBRENMS_VERIFY_SSL`.

Variable names are unique across services, except the Cisco ACI credentials, which are prefixed with `ACI_` to avoid clashing with generic names.

Changing `.env` needs a container recreate, not a rebuild:

```sh
podman compose up -d --force-recreate
```

## Start the cluster

```sh
podman compose up -d --build
```

On Apple Silicon, `cisco-aci-mcp` and `open-webui` run as `linux/amd64` under emulation. Their `arm64` builds crash in `cryptography` (SIGILL) on the Podman VM. The compose file sets `platform: linux/amd64` on those services. Compose ignores that setting for builds, so build the ACI image explicitly:

```sh
podman build --platform linux/amd64 -t cisco-aci-mcp:local cisco-aci-mcp
podman compose up -d --force-recreate
```

Check status and health:

```sh
podman ps
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5100/health
```

MCP healthchecks initialize the local MCP endpoint and close any session created by the check. They verify the MCP server responds, not that its upstream network service or credentials work. A healthcheck reporting `unhealthy` does not itself restart a container. Recreate existing containers after changing the compose file to apply healthcheck configuration.

Stop the cluster:

```sh
podman compose down
```

Named volume `open-webui-data` keeps chats, users, and settings across restarts. `podman compose down -v` deletes it.

## Open WebUI

Open http://localhost:5100 and sign in with Microsoft or the local admin.

The Entra app registration needs this redirect URI:

```
http://localhost:5100/oauth/microsoft/callback
```

`TOOL_SERVER_CONNECTIONS` is applied only when the Open WebUI volume is first created. For an existing volume, add or change tool servers in Settings → Tools, or through the admin API. See [open-webui/README.md](./open-webui/README.md).

## Adding or changing an MCP service

1. Create a folder with a Dockerfile that builds from a pinned upstream ref.
2. Add the service to `compose.yaml` with a `127.0.0.1:510X:<container port>` mapping on `mcp-net`.
3. Add its variables to `.env.example` and `.env`, and reference them in the service's `environment:` block.
4. Add its URL to `TOOL_SERVER_CONNECTIONS` (the container-internal URL, for example `http://name:port/mcp`).
5. Recreate the cluster and check the endpoint returns HTTP 200 for an MCP `initialize` request.

Per-service notes:

- [open-webui/README.md](./open-webui/README.md)
- [fortigate-mcp/README.md](./fortigate-mcp/README.md)
- [opensearch-mcp/README.md](./opensearch-mcp/README.md)

## Notes

- Cisco ISE and ACI are verified only as running MCP servers. Live device calls are untested until real credentials are set in `.env`.
- Do not run `podman compose config` without `-q`. It prints resolved secrets to the terminal.
