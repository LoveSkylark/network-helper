---
name: librenms
description: Use to check device status, interface state, or active alerts in LibreNMS for a customer's hosts or network devices.
compatibility: Requires the librenms MCP server (http://librenms-mcp:8000/mcp). Use with the network-core skill.
---

# LibreNMS

Read-only use of the LibreNMS MCP. Follow the customer scoping rules in `network-core`.

## Tools

Use search to find the read operations for devices, ports, and alerts. Confirm the names in the search results.

## Workflow: check a device or customer alerts

1. Identify the device, and map it to a customer with `netbox` if needed.
2. Read the device status and its interface or port state.
3. List active alerts for that device, or for the customer's devices if the scope is the whole customer.
4. Report the status, the time of each alert, and the device name. Do not acknowledge or silence alerts. Describe them and let the operator act.

## Open items

- The exact LibreNMS operation names for devices, ports, and alerts. Confirm them with search.
