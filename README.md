# oci-mcp

An MCP server for operating Oracle Cloud Infrastructure from an MCP-aware agent —
Identity, Compute, Block Volume, Networking (VCN), Object Storage and OKE.

Runs locally over **stdio** and reads credentials straight from `~/.oci/config`,
so they never leave your machine.

> **Status: Phase 0.** Scaffold plus `oci_whoami`. Read, write and delete tool
> phases are still to come — see [Roadmap](#roadmap).

## Requirements

- Python **3.12** (pinned in `.python-version` — the `oci` SDK does not support 3.14)
- [`uv`](https://docs.astral.sh/uv/)
- A working `~/.oci/config`, verifiable with `oci iam region-list`

## Install

```bash
uv sync
```

## Run

```bash
uv run oci-mcp
```

It speaks MCP over stdio, so on its own it just waits on stdin — that is correct
behaviour, not a hang. Normally a client launches it; see
[Register with Claude Code](#register-with-claude-code).

## Test

**Unit tests** — offline, no credentials, no network:

```bash
uv run pytest -q
```

**Inspect the catalog** without writing any client code:

```bash
uv run fastmcp list --command "uv run oci-mcp"
uv run fastmcp list --command "uv run oci-mcp" --output-schema
```

**Call a tool** directly, which is the fastest way to check a change end to end:

```bash
uv run fastmcp call --command "uv run oci-mcp" --target oci_whoami --json
```

Pass tool arguments as `key=value` pairs after `--target`, or use `--input-json`
for nested values.

> Note: point `fastmcp` at the **`--command`**, not at `src/oci_mcp/server.py`.
> Passing the file loads it as a standalone script rather than a package module,
> which breaks its relative imports.

**Check the safety gates** by varying the environment — the fail-closed default
means an unconfigured server can mutate nothing:

```bash
# default: writes enabled but no allowlist -> mutations_possible false
uv run fastmcp call --command "uv run oci-mcp" --target oci_whoami --json

# allowlist set -> mutations_possible true, mutable_compartments [lab]
uv run fastmcp call --command "env OCI_MCP_COMPARTMENTS=lab uv run oci-mcp" \
  --target oci_whoami --json
```

The `env` prefix is load-bearing: `--command` is executed without a shell, so a
bare `VAR=value` prefix would be treated as the program name and fail with
`No such file or directory`.

**Verify the client sees it:**

```bash
claude mcp list        # expect: oci: ... - ✔ Connected
```

## Configure

All settings are environment variables; see [.env.example](.env.example). The
defaults fail closed — writes are enabled but the compartment allowlist is empty,
so no mutating call can succeed until you name a compartment.

| Variable | Default | Purpose |
|---|---|---|
| `OCI_CLI_PROFILE` | `DEFAULT` | Profile in `~/.oci/config` |
| `OCI_MCP_REGION` | profile's region | Region override |
| `OCI_MCP_ALLOW_WRITE` | `true` | Register write tools |
| `OCI_MCP_ALLOW_DELETE` | `false` | Register delete tools |
| `OCI_MCP_COMPARTMENTS` | *(empty)* | Compartments where mutation is permitted. **Empty = none.** |
| `OCI_MCP_AUDIT_LOG` | `~/.oci-mcp/audit.jsonl` | Mutation audit trail |

## Register with Claude Code

A stdio server does **not** inherit your shell environment — the client supplies it.
So pass any non-default settings with `--env`, or they are silently ignored:

```bash
claude mcp add oci \
  --env OCI_MCP_COMPARTMENTS=lab \
  -- uv --directory "$PWD" run oci-mcp
```

Verify by asking the agent to call `oci_whoami`; its `permissions.notes` will say
plainly why a mutation would be refused.

## Safety model

Four independent layers, none of which rely on client cooperation:

1. **Capability flags** enforced at registration — a disabled capability's tools
   are absent from the catalog, not merely refusing when called.
2. **Compartment allowlist** — every mutating call resolves its target's
   compartment and is rejected outside the list.
3. **Two-phase confirm tokens** — destructive tools first return a preview plus a
   short-lived HMAC token bound to that exact operation and OCID; nothing is
   destroyed until the token is echoed back.
4. **Append-only audit log** of every mutation.

## Tools

| Tool | Notes |
|---|---|
| `oci_whoami` | Active tenancy, user, region, auth method, and this server's own permissions |

## Roadmap

| Phase | Scope |
|---|---|
| 0 ✅ | Scaffold, config, lazy clients, `oci_whoami` |
| 1 | Read layer — `oci_list`, `oci_get`, `oci_search` over ~20 resource types |
| 2 | Safety — confirm tokens, allowlist guard, audit log |
| 3 | Compute + Block Volume lifecycle |
| 4 | Networking — VCN composite, security rules, `oci_get_network_path` diagnostic |
| 5 | Object Storage + OKE + work requests |

Target surface is roughly 26 tools: reads collapse into three dispatch tools since
their schemas are uniform, while writes stay explicit because theirs are not.
