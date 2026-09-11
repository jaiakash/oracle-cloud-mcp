# Contributing

Thanks for your interest. This project is an MCP server that lets an AI agent
operate Oracle Cloud Infrastructure. Bug reports, new resource types and
documentation fixes are all welcome.

## Prerequisites

- **[uv](https://docs.astral.sh/uv/)** — manages the interpreter and dependencies.
- **Python 3.12.** Pinned in `.python-version`; `uv` fetches it for you. The `oci`
  SDK publishes classifiers only through 3.13 and `pyproject.toml` caps
  `requires-python` at `<3.14`, so a newer interpreter will not resolve.
- **An OCI account — only if you want to run live checks.** The unit test suite is
  entirely offline. You can contribute without any OCI access at all.

## Setup

```bash
git clone https://github.com/jaiakash/oracle-cloud-mcp.git
cd oracle-cloud-mcp
uv sync
uv run pre-commit install   # optional, but saves a CI round-trip
```

## Running the tests

```bash
uv run pytest -q
```

No credentials, no network, no OCI account. If a test you add needs either, it
belongs behind an explicit opt-in environment variable.

## Lint and format

The same two commands CI runs:

```bash
uv run ruff check .
uv run ruff format --check .
```

`uv run pre-commit install` wires these into your commits so you find problems
before pushing. The ruff version in `pyproject.toml` is pinned to match the `rev`
in `.pre-commit-config.yaml` — **if you bump one, bump the other**, or local and
CI will enforce different rules.

## Calling a tool by hand

To exercise the server without an MCP client:

```bash
C="uv run oci-mcp"

# what tools exist
uv run fastmcp list --command "$C"

# call one
uv run fastmcp call --command "$C" --target oci_whoami --json

uv run fastmcp call --command "$C" --target oci_list \
  --input-json '{"resource_type":"instance","lifecycle_state":"RUNNING"}' --json
```

Two gotchas worth knowing:

- **Arguments must go through `--input-json`.** With `--command` in play, a bare
  `key=value` positional is parsed as a server spec and fails with
  `Cannot use both a server spec and --command`.
- **Point `fastmcp` at `--command`, not at `src/oci_mcp/server.py`.** Passing the
  file loads it as a standalone script rather than a package module, which breaks
  its relative imports.

A stdio server started on its own (`uv run oci-mcp`) just waits on stdin. That is
correct, not a hang.

## How to add a resource type

**This is the best first contribution.** Adding a type to `oci_list` / `oci_get` is
usually a single entry in `REGISTRY` in
[`src/oci_mcp/registry.py`](src/oci_mcp/registry.py). No new tool, no dispatch code.

```python
"vlan": ResourceKind(
    service="network",
    list_fn=lambda: clients.network().list_vlans,
    get_fn=lambda: clients.network().get_vlan,
    fields=(*_ID, "vcn_id", "cidr=cidr_block", "ad=availability_domain"),
),
```

### The pieces

**`list_fn` / `get_fn` are zero-argument lambdas**, not the methods themselves.
That is deliberate: it defers building the service client until first use, so
importing the module never needs credentials. If the service client you need
doesn't exist yet, add a small `@cache` factory to `clients.py`.

`get_fn` is optional — omit it when the API has no get operation (`shape`,
`availability_domain`) and `oci_get` will say so helpfully.

**`fields` is the projection.** Each entry is `"key"` or `"key=attribute"`:

```python
"shape"                     # same name in output and on the model
"name=display_name"         # renamed
"ocpus=shape_config.ocpus"  # dotted path into a nested model
```

Dotted paths let you lift one scalar out of a sub-object instead of embedding the
whole thing. A missing attribute yields `None` rather than raising, so a spec can
cover resources that only sometimes carry a field.

**Why project at all?** An OCI `Instance` serialises to 36 fields, mostly null.
Returning a handful of those raw would exhaust an agent's context for no benefit.
Keep projections to the fields that *identify and locate* a resource — name, OCID,
state, size, where it lives. Callers pass `verbose=true` when they want everything.
Always include a `name` key; a test enforces it.

### Flags for irregular APIs

Most list calls are `fn(compartment_id=...)`. These flags cover the ones that
aren't, so no caller has to know:

| Flag | Use when |
|---|---|
| `needs_ad=True` | The list API is availability-domain scoped (`list_boot_volume_attachments`). The engine fans out across ADs. |
| `needs_namespace=True` | Object Storage: the tenancy namespace is injected for you. |
| `get_by_name=True` | `get` takes a name rather than an OCID (buckets). |
| `list_kwargs={...}` | The API demands a discriminator the caller shouldn't supply, e.g. `{"scope": "REGION"}` for `list_public_ips`. |
| `scope="tenancy"` | Results are identical in every compartment, so query the root once (`availability_domain`). |
| `scope="global"` | No compartment at all (`region`). |
| `paginated=False` | The API returns everything in one unpaged call and rejects the pagination helper's kwargs. |

Use `note=` for anything a caller would otherwise get wrong — it is returned with
the results. For example, OKE clusters are not indexed by Resource Search, so
`cluster` carries a note pointing people at `oci_list` instead of `oci_search`.

### Verifying it

The tests in `tests/test_registry.py` are parametrised over `REGISTRY`, so **your
new type is covered automatically** — the test count goes up on its own:

```bash
uv run pytest -q          # 206 passed  ->  210 passed
```

Those checks catch a bad service name, a malformed field spec, a missing `name`
key, and flag combinations that can't work. If you have OCI access, also confirm
it against a real tenancy:

```bash
uv run python -c "
from oci_mcp import reads
print(reads.list_resources('vlan', compartment='your-compartment'))
"
```

An empty list is a pass. An exception is not.

## Pull requests

- **One logical change per PR.** If you reformat while fixing a bug, put the
  formatting in its own commit.
- **Tests and lint must pass.** CI runs `pytest` on Python 3.12 and 3.13, plus
  `ruff check` and `ruff format --check`.
- **Say how you verified it.** "Added the type, tests went 206 → 210, listed it
  against my tenancy and got 3 rows" is exactly right.
- Commit messages: a short imperative summary, then *why* rather than *what* — the
  diff already says what.

## Project layout

| Path | Role |
|---|---|
| `src/oci_mcp/server.py` | FastMCP instance; registers tools conditionally on the capability flags |
| `src/oci_mcp/config.py` | Environment settings. No OCI SDK import, so it stays testable without credentials |
| `src/oci_mcp/clients.py` | Lazy, cached service clients |
| `src/oci_mcp/compartments.py` | Compartment name → OCID resolution and the allowlist |
| `src/oci_mcp/registry.py` | **The resource-type table — usually the only file you need** |
| `src/oci_mcp/shaping.py` | Projections; the verbose escape hatch |
| `src/oci_mcp/reads.py` | Read execution: compartment sweep, filtering, truncation |
| `src/oci_mcp/tools/read.py` | The MCP tools themselves |

## Safety, if you touch write paths

Reads collapse into three dispatch tools because their schemas are uniform.
Writes will stay explicit, because theirs are not — don't add a generic
`oci_create(resource_type, spec)`.

Mutating tools must respect the compartment allowlist, and an unconfigured
allowlist means **no mutation anywhere**. That default is intentional: a server
that silently permitted tenancy-wide writes when unconfigured would defeat the
point of having an allowlist. Please don't relax it.

## Code of conduct

Be decent to each other. Assume good faith, keep review feedback about the code.
