---
name: netbox
description: Use to map IP addresses, subnets, devices, or sites in NetBox to a customer, tenant, or datacenter, or to confirm inventory for a network investigation.
compatibility: Requires the netbox MCP server (http://netbox-mcp:8000/mcp), backed by netbox.vist.is. Use with the network-core skill.
---

# NetBox

Read-only use of the NetBox MCP against `netbox.vist.is`. NetBox is the inventory of record for IP addresses and devices. Follow the customer scoping rules in `network-core`.

## Tools

Use search to find the read operations you need, for example prefixes, IP addresses, devices, sites, and tenants. Confirm the names in the search results.

## Workflow: map an IP or subnet to a customer

1. Look up the prefix or IP address.
2. Read its tenant, site, and related device or interface.
3. Check the customer code against the rules in `network-core`. If the mapping is missing or conflicting, report it instead of guessing.
4. Report the result with the NetBox object IDs and the datacenter.

## Open items

- The NetBox tenant and site naming used to map customers. Confirm it before relying on tenant names.
