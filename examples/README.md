# Compose Examples

These examples show how to add another MCP instance with its own service name, credentials, and network. They reuse the existing images; they do not replace the main services.

| Example | Connection variables |
| --- | --- |
| [compose.fortios.yaml](compose.fortios.yaml) | `FORTIOS_EXAMPLE_HOST`, `FORTIOS_EXAMPLE_API_TOKEN`, `FORTIOS_EXAMPLE_VDOM`, `FORTIOS_EXAMPLE_VERIFY_SSL`, `FORTIOS_EXAMPLE_TIMEOUT` |
| [compose.netbox.yaml](compose.netbox.yaml) | `NETBOX_EXAMPLE_URL`, `NETBOX_EXAMPLE_TOKEN`, `NETBOX_EXAMPLE_VERIFY_SSL` |
| [compose.opensearch.yaml](compose.opensearch.yaml) | `OPENSEARCH_EXAMPLE_URL`, `OPENSEARCH_EXAMPLE_AUTH_MODE`, `OPENSEARCH_EXAMPLE_TOKEN`, `OPENSEARCH_EXAMPLE_USERNAME`, `OPENSEARCH_EXAMPLE_PASSWORD`, `OPENSEARCH_EXAMPLE_SSL_VERIFY` |

## Add an Instance

1. Copy the chosen example's MCP service and network into [compose.mcp.yaml](../compose.mcp.yaml). Give the new service and network unique names. Reuse the same image, but give each instance its own connection variables.
2. Set those variables in the root `.env`, using the actual device address and its own credentials. The example variable names above can be renamed; the names inside the container, such as `FORTIOS_HOST`, must stay as shown. Never commit credentials. For OpenSearch authentication modes, see the [OpenSearch guide](../mcp/opensearch/README.md).
3. Add the new network to LibreChat's `networks` list in [compose.yaml](../compose.yaml). For Podman, also add it to [compose.podman.yaml](../compose.podman.yaml) using the existing isolation settings.
4. Register the server in [librechat.yaml](../librechat/librechat.yaml) as shown below, and create its matching context file in [network-context/](../network-context/).
5. Apply the configuration and select the new server's tools in a LibreChat agent, as described below.

The example health checks only verify that the MCP port accepts TCP connections, not that the MCP endpoint or upstream credentials work.

## LibreChat Registration

Adding a service does not register it in LibreChat. Add its address to `mcpSettings.allowedDomains` and a matching entry under `mcpServers` in [librechat.yaml](../librechat/librechat.yaml). For FortiOS, for example:

```yaml
mcpSettings:
  allowedDomains:
    - "http://fortios-example:8000"

mcpServers:
  fortios-example:
    title: "Example FortiGate"
    type: streamable-http
    url: http://fortios-example:8000/mcp
    chatMenu: false
```

Add these entries to the existing lists and mappings; do not replace the other servers. For NetBox, use `netbox-example:8000`; for OpenSearch, use `opensearch-example:9900`, add `OPENSEARCH_EXAMPLE_TOKEN` to LibreChat's environment in [compose.yaml](../compose.yaml), and add a `headers` mapping with `Authorization: "Bearer ${OPENSEARCH_EXAMPLE_TOKEN}"`. LibreChat passes this header to the OpenSearch MCP server, which uses the configured authentication mode for the upstream request.

The `title` distinguishes the server in LibreChat; the key `fortios-example` identifies it in configuration. Create a file named `fortios-example.md` in [network-context/](../network-context/) to match that key. The file provides context when the server's tools are available to an agent. Context can be sent to Copilot and is tracked in Git, so do not put credentials or sensitive network details in it.

## Apply Changes

From the project root, check the configuration, start the services, then regenerate the LibreChat configuration and recreate LibreChat:

```sh
docker compose config --quiet
docker compose up -d --build
docker compose run --rm --no-deps librechat-context-init
docker compose up -d --no-deps --force-recreate librechat
```

For Podman, add `-f compose.yaml -f compose.podman.yaml` to each command. Then select the new server's tools in an agent. The existing automatic approval list applies only to the named servers listed there; new instance tools require approval unless explicitly added.

Review upstream account permissions and use read-only credentials where possible.