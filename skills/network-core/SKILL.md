---
name: network-core
description: Use for any datacenter network question involving customers, VDOMs, ACI tenants, or firewalls. Sets customer scoping, environment facts, and security rules. Attach to every network agent.
compatibility: Shared base for the fortios, cisco-aci, netbox, and librenms skills. Requires no MCP server itself.
---

# Network Core

Shared rules and environment facts for the network skills. Read-only: describe changes, do not make them.

## Environment

- Two datacenters. **DC2 is primary**. DC1 is the secondary site.
- Internet: DC2 has two ISPs (Siminn and Nova). DC1 has one (Siminn).
- Firewalls: FortiGates `dc1-fw-fgt01` and `dc2-fw-fgt01`, active-standby with a shared configuration. Customers are separated by VDOM. **TO CONFIRM:** whether each site has its own FortiGate or both share one pair.
- Fabric: Cisco ACI, each customer has one or more tenants with VRFs.
- IPAM and inventory: NetBox. Monitoring: LibreNMS.

## Customers and network names

- Each customer has a 4-letter uppercase code. The same code is used in JIRA tickets.
- Shared and internal networks use Z or X prefixes. Known examples:
  - `ZACI`: core ACI network, shared by all tenants (not a customer).
  - `ZDMZ`: shared DMZ environment.
  - `XXEV`: corporate firewall environment.
  - `HARP`: customer Harpa.
- **TO CONFIRM:** the exact rule that maps a VDOM, VRF, or tenant name to a customer code. Do not infer it from name shape. Look it up in NetBox or FortiGate, or ask the operator.

## Customer scoping rules

1. Identify the customer before investigating. If it is unclear, ask.
2. Never switch to another customer's VDOM or tenant without asking first.
3. Assume you are still on the same customer when you move between MCP servers, unless the user says otherwise.
4. State the active customer code and datacenter at the top of every answer.

## Security

- Never print credentials, API tokens, passwords, or secrets. Replace them with `[redacted]`.
- Skill files are tracked in Git and sent to Copilot. Do not add IPs, tokens, or customer-sensitive details to them.

## Output

- Say which MCP server each fact came from.
- Mark unverified items clearly. Do not fill gaps with assumptions.
- Do not recommend changes as done. Describe them and let the operator carry them out.

## Related skills

- `fortios`: firewall policies, VDOMs, routes, logs (FortiGate MCP).
- `cisco-aci`: tenants, VRFs, L3Outs (ACI MCP).
- `netbox`: IP, device, and subnet inventory (NetBox MCP).
- `librenms`: device status and alerts (LibreNMS MCP).
