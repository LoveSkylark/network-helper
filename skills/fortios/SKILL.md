---
name: fortios
description: Use when auditing FortiGate firewall policies, VDOMs, addresses, routes, sessions, or traffic logs for a customer, including finding unused firewall policies.
compatibility: Requires the fortios MCP server (http://fortios-mcp:8000/mcp). Use with the network-core skill.
---

# FortiGate

Read-only use of the FortiGate MCP. FortiGates are `dc1-fw-fgt01` and `dc2-fw-fgt01`. Follow the customer scoping rules in `network-core`, and never switch VDOM without asking first.

## Tools

The server is a compact catalog. Use these directly:

- `cmdb_list` and `cmdb_get`: configuration objects, such as firewall policies, addresses, and VDOMs.
- `monitor_get`: live status and counters, such as policy hit counts and sessions.
- `log_get`: traffic and event logs.

For anything else, call `search_tools` with a short description, then run the match with `call_tool`. Example upstream name: `system_vdom_list`.

The FortiGate API token can write objects. Use a read-only API profile, and only call read operations.

## Workflow: find unused firewall policies

1. Confirm the customer, FortiGate, and VDOM. Ask if unclear.
2. Use `cmdb_list` to list the policies in that VDOM.
3. Use `monitor_get` to get hit counts or last-used data for those policies. If the operation name is unknown, search for it first.
4. List policies with zero hits over the period. Check `log_get` for recent traffic if the counters are unreliable.
5. Report the policy IDs, names, and the period checked. Do not recommend removing a policy without confirming it with the operator.

## Open items

- The operation that returns policy hit counts. Confirm it with `search_tools` against the live server.
