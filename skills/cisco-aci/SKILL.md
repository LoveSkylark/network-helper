---
name: cisco-aci
description: Use when tracing how a Cisco ACI tenant reaches the outside, or looking up tenants, VRFs, bridge domains, L3Outs, and contracts in the APIC.
compatibility: Requires the cisco-aci MCP server (http://cisco-aci-mcp:8000/mcp), backed by apic.vist.is. Use with the network-core skill.
---

# Cisco ACI

Read-only use of the ACI MCP against `apic.vist.is`. Follow the customer scoping rules in `network-core`.

## Tools

The server has a search transform. Use `search_tools` to find read operations for tenants, VRFs, bridge domains, L3Outs, and contracts. Confirm the exact operation names in the search results. Do not guess them.

## Workflow: trace how an ACI tenant reaches the outside

This skill covers the ACI half. For the firewall half, use the `fortios` skill with the same customer and VDOM.

1. Identify the customer and the ACI tenant.
2. List the VRFs and any L3Outs or external EPGs. Note the next hop for each.
3. Check whether the VRF has an L3Out to the firewall, or a L2 path. Also check the default gateway for each subnet.
4. Hand off to `fortios` to find the matching interface, route, and policies in the customer's VDOM.
5. Use `netbox` to confirm subnets and IPs.
6. Report the path as a list of hops, with the source for each hop. Mark any hop you could not verify.

## Open items

- The exact ACI operation names for tenant, VRF, and L3Out lookups. Confirm them with search.
