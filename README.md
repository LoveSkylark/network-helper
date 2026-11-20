# MCP cluster

Open WebUI is the front end, with several MCP services behind it. A Copilot SDK Pipe supplies the chat models, and Open WebUI uses the MCP services as tools. Everything starts from one compose file in this folder.

## Services

| Service | Folder | Host port | Container port | Purpose |
|---|---|---|---|---|
| open-webui | `copilot-webui/` | 80 | 8080 | Chat UI, Copilot SDK, and Microsoft sign-in |
| fortios-mcp | `fortigate-mcp/` | not published | 8000 | FortiGate / FortiOS tools |
| opensearch-mcp | `opensearch-mcp/` | not published | 9900 | OpenSearch tools |
| cisco-ise-mcp | `cisco-ise-mcp/` | not published | 5000 | Cisco ISE tools |
| cisco-aci-mcp | `cisco-aci-mcp/` | not published | 8000 | Cisco ACI tools |
| netbox-mcp | `netbox-mcp/` | not published | 8000 | NetBox tools (read-only) |
| librenms-mcp | `librenms-mcp/` | not published | 8000 | LibreNMS tools (read-only by default) |

The LibreNMS MCP exits at startup until `LIBRENMS_TOKEN` is set in `.env`. Its `READ_ONLY_MODE` is `true` in compose, so it can't make write calls.

Only Open WebUI publishes a host port, `80`, on all interfaces. Restrict access with a firewall and use HTTPS through a reverse proxy for remote access; the published port itself serves HTTP.

Each MCP service has its own bridge network shared with Open WebUI, which connects by service name (for example `http://fortios-mcp:8000/mcp`). MCP services do not share a Compose network with each other, and their ports are not published to the host. For Podman, use the commands below with [compose.podman.yaml](./compose.podman.yaml): its `isolate` setting blocks direct traffic between these networks. Docker users use the base Compose file and should verify their host firewall enforces bridge-network isolation. The networks allow outbound access to integrations and do not replace host and network firewall rules. Open WebUI's `TOOL_SERVER_CONNECTIONS` in [compose.yaml](./compose.yaml) lists the MCP endpoints.

The container runtime allocates the bridge subnets. Configure its address pools so they do not overlap local, VPN, or remote integration networks. Changing a runtime's address pools does not move existing networks: recreate the affected networks and their attached containers to apply the new ranges. Docker's default bridge is configured separately from its default address pools; Podman has its own network configuration.

## Layout

```
compose.yaml          Cluster definition
compose.podman.yaml   Podman bridge-network isolation override
.env                  All configuration and secrets for every container
open-webui/           Open WebUI deployment notes
copilot-webui/        Open WebUI image with the Copilot SDK Pipe
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

- **Open WebUI:** `WEBUI_URL` (the externally reachable URL without a trailing slash), `WEBUI_SECRET_KEY` (generate with `openssl rand -hex 32`), the local admin (`WEBUI_ADMIN_*`), and the Microsoft Entra values (`MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_CLIENT_TENANT_ID`).
- **GitHub Copilot:** `COPILOT_GITHUB_TOKEN`, a personal fine-grained token with the Copilot Requests account permission. The token's account must have Copilot access.
- **FortiOS:** `FORTIOS_HOST`, `FORTIOS_API_TOKEN`, `FORTIOS_VDOM`, `FORTIOS_VERIFY_SSL`.
- **OpenSearch:** `OPENSEARCH_URL`, `OPENSEARCH_USERNAME`, `OPENSEARCH_PASSWORD`, `OPENSEARCH_SSL_VERIFY`.
- **Cisco ISE:** `ISE_IP`, `API_USERNAME`, `API_PWD`, certificate verification flags.
- **Cisco ACI:** `APIC_URL`, `ACI_USERNAME`, `ACI_PASSWORD`. These map to the `USERNAME` and `PASSWORD` variables the upstream server reads.
- **NetBox:** `NETBOX_URL`, `NETBOX_TOKEN`, `NETBOX_VERIFY_SSL`.
- **LibreNMS:** `LIBRENMS_URL`, `LIBRENMS_TOKEN`, `LIBRENMS_VERIFY_SSL`.

Variable names are unique across services, except the Cisco ACI credentials, which are prefixed with `ACI_` to avoid clashing with generic names.

Changing `.env` needs a container recreate, not a rebuild:

```sh
podman compose -f compose.yaml -f compose.podman.yaml up -d --force-recreate
```

## Start the cluster

```sh
podman compose -f compose.yaml -f compose.podman.yaml up -d --build
```

For Docker, use `docker compose up -d --build` instead; do not apply the Podman override. Always include both `-f` options when using Podman Compose.

Compose no longer forces an architecture. On Apple Silicon Podman VMs, native ARM builds of `cisco-aci-mcp` and `open-webui` previously crashed with SIGILL in `cryptography`; verify they start successfully in your environment.

Check status and health:

```sh
podman ps
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/health
```

MCP healthchecks initialize the local MCP endpoint and close any session created by the check. They verify the MCP server responds, not that its upstream network service or credentials work. A healthcheck reporting `unhealthy` does not itself restart a container. Recreate existing containers after changing the compose file to apply healthcheck configuration.

Stop the cluster:

```sh
podman compose -f compose.yaml -f compose.podman.yaml down
```

Named volume `open-webui-data` keeps chats, users, and settings across restarts. Adding `-v` to the `down` command deletes it.

## Configuration tests

Run the Compose configuration checks from the project root:

```sh
python3 -m unittest discover -s tests -v
```

The tests require Python 3 and Podman Compose or Docker Compose. They render both configurations using `.env.example`, not the real `.env`, and do not start containers. Set `COMPOSE_RUNTIME=docker` or `COMPOSE_RUNTIME=podman` to select a runtime when both are installed. These checks do not verify runtime connectivity or firewall isolation.

After building the Open WebUI image, run the Copilot Pipe tests without network access:

```sh
docker run --rm --network none -v "$PWD/copilot-webui:/work:ro" -w /work -e PYTHONPATH=/app/backend -e WEBUI_SECRET_KEY=local-test-only-not-a-real-secret --entrypoint python network-helper-copilot-webui:local -B -m unittest -v test_copilot_pipe
```

## Open WebUI

Open the URL configured in `WEBUI_URL` and sign in with Microsoft or the local admin. For direct remote access, set it to `http://<server-address>`; use the HTTPS URL instead if a reverse proxy terminates TLS.

An administrator must register the Copilot Pipe before selecting a Copilot model. See [open-webui/README.md](./open-webui/README.md). Requests use the shared Copilot account. Selected MCP tool calls require confirmation and can modify network devices; restrict access appropriately.

The Entra app registration needs this redirect URI:

```
<WEBUI_URL>/oauth/microsoft/callback
```

`TOOL_SERVER_CONNECTIONS` is applied only when the Open WebUI volume is first created. For an existing volume, add or change tool servers in Settings → Tools, or through the admin API. See [open-webui/README.md](./open-webui/README.md).

## Adding or changing an MCP service

1. Create a folder with a Dockerfile that builds from a pinned upstream ref.
2. Add a dedicated bridge network and connect both the service and Open WebUI to it, without publishing an MCP host port. Add the network to `compose.podman.yaml` as well.
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
