# oci-mcp

Operate Oracle Cloud Infrastructure from an AI agent.

An [MCP](https://modelcontextprotocol.io) server that exposes OCI — compute, block
storage, networking, OKE, database, object storage and identity — as tools an agent
can call, so you can ask for things instead of assembling `oci` CLI invocations and
copying OCIDs between them.

```
"which of my instances are running?"
"what's in the test-deploy-kubeflow compartment?"
"show me the config for my OKE cluster"
```

It runs locally over stdio and reads credentials straight from `~/.oci/config`, so
they never leave your machine.

> **Status:** read-only today. Create and modify tools are planned — see
> [open issues](https://github.com/jaiakash/oracle-cloud-mcp/issues).

## Requirements

- **Python 3.12** — pinned in `.python-version`; `uv` fetches it. The `oci` SDK
  does not support 3.14.
- **[uv](https://docs.astral.sh/uv/)**
- **A working `~/.oci/config`.** Verify with `oci iam region-list`.

## Install

```bash
git clone https://github.com/jaiakash/oracle-cloud-mcp.git
cd oracle-cloud-mcp
uv sync
```

## Run

```bash
uv run oci-mcp
```

This speaks MCP over stdio, so on its own it just waits on stdin — that is correct,
not a hang. Normally your client launches it.

## Add to your MCP client

**Claude Code:**

```bash
claude mcp add oci -- uv --directory "$PWD" run oci-mcp
```

**Cursor, VS Code, Zed and others** take the same command as JSON:

```json
{
  "mcpServers": {
    "oci": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/oracle-cloud-mcp", "run", "oci-mcp"]
    }
  }
}
```

A stdio server inherits nothing from your shell, so any setting from
[Configure](#configure) has to be passed by the client:

```bash
claude mcp add oci --env OCI_MCP_COMPARTMENTS=lab -- uv --directory "$PWD" run oci-mcp
```

Confirm it connected by asking the agent to call `oci_whoami`.

## Tools

| Tool | What it does |
|---|---|
| `oci_whoami` | Active tenancy, user, region and auth method, plus which compartments this server may modify. Cheap orientation call. |
| `oci_list` | List one resource type. Omit `compartment` to sweep the whole tenancy; each row is tagged with where it came from. Filter with `lifecycle_state`. |
| `oci_get` | Full detail for one resource by OCID — or by name, for buckets. |
| `oci_search` | Find anything across the tenancy in one call, by structured query or free text. |

Reads collapse into three dispatch tools because their schemas are uniform: "show me
*type* in *compartment*". Results are projected down to the fields that identify and
locate a resource — an OCI `Instance` has 36 fields, most of them null — with
`verbose=true` to get the full object.

### Resource types

Pass any of these as `resource_type`:

| Service | Values |
|---|---|
| compute | `instance` `image` `shape` `vnic_attachment` `volume_attachment` `boot_volume_attachment` |
| block storage | `volume` `boot_volume` `volume_backup` `boot_volume_backup` `volume_group` |
| network | `vcn` `subnet` `security_list` `nsg` `route_table` `internet_gateway` `nat_gateway` `service_gateway` `drg` `dhcp_options` `public_ip` `load_balancer` |
| OKE | `cluster` `node_pool` `virtual_node_pool` |
| database | `autonomous_database` `db_system` `db_home` `db_node` `mysql_db_system` `nosql_table` |
| object storage | `bucket` |
| identity | `compartment` `user` `group` `policy` `availability_domain` `region` |

Two quirks worth knowing:

- **OKE clusters are not indexed by OCI Resource Search**, so `oci_search` will never
  return one. Use `oci_list("cluster")`.
- **Buckets are addressed by name**, not OCID: `oci_get("bucket", "my-bucket")`.

## Configure

Everything is an environment variable, and every default is safe. See
[`.env.example`](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `OCI_CLI_PROFILE` | `DEFAULT` | Profile in `~/.oci/config` |
| `OCI_MCP_REGION` | profile's region | Region override |
| `OCI_MCP_COMPARTMENTS` | *(empty)* | Compartments where mutation is permitted. **Empty means none.** |
| `OCI_MCP_ALLOW_WRITE` | `true` | Register write tools |
| `OCI_MCP_ALLOW_DELETE` | `false` | Register delete tools |

The allowlist fails closed: an unconfigured server cannot mutate anything, anywhere.
Name a disposable compartment to enable writes — never the root. A disabled
capability's tools are absent from the catalog entirely rather than present and
refusing, so an agent cannot be talked into calling one.

`oci_whoami` reports the active allowlist and flags, and explains why a mutation
would be refused.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Adding a new
resource type is usually a single entry in `registry.py` and the test suite covers it
automatically, which makes it a good first change.

## License

[Apache License 2.0](LICENSE).
