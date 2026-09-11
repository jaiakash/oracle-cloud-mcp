# oci-mcp

An MCP server for operating Oracle Cloud Infrastructure from an MCP-aware agent —
Identity, Compute, Block Volume, Networking (VCN), Object Storage and OKE.

Runs locally over **stdio** and reads credentials straight from `~/.oci/config`,
so they never leave your machine.

> **Status: Phase 1.** Read-only — orientation, list, get and search across
> 39 resource types. Write and delete phases are still to come — see
> [Roadmap](#roadmap).

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

Pass tool arguments with `--input-json '{...}'`. (Bare `key=value` pairs only
work when you give a server *file* instead of `--command`, which this package
cannot do — see the note below.)

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
| `oci_list` | List one resource type. Omit `compartment` to sweep the tenancy; rows are tagged with where they came from |
| `oci_get` | Full detail for one resource by OCID (buckets: by name) |
| `oci_search` | Tenancy-wide Resource Search — structured query or free text |

Reads collapse into three dispatch tools because their schemas are uniform:
"show me *type* in *compartment*". Writes will stay explicit because theirs are not.

### Resource types

| Service | `resource_type` values |
|---|---|
| compute | `instance` `image` `shape` `vnic_attachment` `volume_attachment` `boot_volume_attachment` |
| block_storage | `volume` `boot_volume` `volume_backup` `boot_volume_backup` `volume_group` |
| network | `vcn` `subnet` `security_list` `nsg` `route_table` `internet_gateway` `nat_gateway` `service_gateway` `drg` `dhcp_options` `public_ip` `load_balancer` |
| oke | `cluster` `node_pool` `virtual_node_pool` |
| database | `autonomous_database` `db_system` `db_home` `db_node` `mysql_db_system` `nosql_table` |
| object_storage | `bucket` |
| identity | `compartment` `user` `group` `policy` `availability_domain` `region` |

Every list is projected to the handful of fields that identify and locate a
resource; pass `verbose=true` for the full object. An OCI `Instance` has 36
fields, so this is the difference between a usable answer and a blown context.

Things worth knowing:

- **OKE clusters are not indexed by Resource Search.** `oci_search` will never
  return one; use `oci_list('cluster')`.
- **Buckets are addressed by name**, not OCID: `oci_get('bucket', 'my-bucket')`.
- `boot_volume_attachment` is availability-domain scoped; the server fans out
  across ADs for you.
- Nothing in the `database` group has been exercised against real resources —
  this tenancy has none — but every call is verified to return an empty list
  rather than an error.

### Examples

```bash
C="uv run oci-mcp"

# every running instance in the tenancy
uv run fastmcp call --command "$C" --target oci_list \
  --input-json '{"resource_type":"instance","lifecycle_state":"RUNNING"}' --json

# OKE clusters in one compartment
uv run fastmcp call --command "$C" --target oci_list \
  --input-json '{"resource_type":"cluster","compartment":"test-deploy-kubeflow"}' --json

# one bucket, by name
uv run fastmcp call --command "$C" --target oci_get \
  --input-json '{"resource_type":"bucket","target":"terraform-state-kubeflow"}' --json

# anything, anywhere, by structured query
uv run fastmcp call --command "$C" --target oci_search \
  --input-json '{"query":"query all resources where lifecycleState = '"'"'RUNNING'"'"'"}' --json
```

Arguments must go through `--input-json` here: with `--command` in play, a bare
`key=value` positional is parsed as a server spec and fails with
`Cannot use both a server spec and --command`.

## Roadmap

| Phase | Scope |
|---|---|
| 0 ✅ | Scaffold, config, lazy clients, `oci_whoami` |
| 1 ✅ | Read layer — `oci_list`, `oci_get`, `oci_search` over 39 resource types |
| 2 | Safety — compartment allowlist guard and audit log, landed before any write exists |
| 3 | Create and modify — explicit tools for instances, volumes, VCNs/subnets, buckets, OKE node pools |

Scope is deliberately **list, create, modify**. Delete/terminate is not planned;
the `OCI_MCP_ALLOW_DELETE` flag exists so it can be added later without
touching the architecture, but it stays `false` and registers nothing today.

Reads collapse into three dispatch tools since their schemas are uniform, while
writes stay explicit because theirs are not.

## License

[Apache License 2.0](LICENSE).
