---
name: Bug report
about: Something behaves differently than documented
title: ''
labels: bug
assignees: ''
---

## What happened

## What you expected instead

## The exact tool call

<!--
The full command or MCP call, plus the output. For example:

uv run fastmcp call --command "uv run oci-mcp" --target oci_list \
  --input-json '{"resource_type":"instance"}' --json
-->

```
```

## Environment

- **OCI region:** <!-- e.g. us-ashburn-1 -->
- **Python version:** <!-- uv run python -V -->
- **oci-mcp version / commit:**
- **MCP client:** <!-- Claude Code, Cursor, fastmcp CLI, ... -->
- **Auth method:** <!-- API key or session token -->

## `oci_whoami` output

<!--
Usually the fastest way to diagnose a permissions or configuration problem.

REDACT EVERY OCID BEFORE PASTING. The output contains your tenancy and user
OCIDs, and one for each allowlisted compartment under
permissions.mutable_compartments. The useful parts for diagnosis are the region,
auth_method, the capability flags and the `notes` array — not the identifiers.
-->

```
```

## Anything else

<!-- Does the equivalent `oci` CLI command work? That separates a bug here from a tenancy permissions issue. -->
