# AGENTS.md

Instructions for AI coding agents working in this repository.
Humans: see [CONTRIBUTING.md](CONTRIBUTING.md), which covers the same ground at more length.

## What this project is

An MCP server that exposes Oracle Cloud Infrastructure to AI agents. It runs locally
over stdio and reads credentials from `~/.oci/config`. Today it is **read-only**: four
tools over 39 resource types. Create and modify tools are planned but not written.

## Setup and verification

```bash
uv sync                          # Python 3.12 is pinned; uv fetches it
uv run pytest -q                 # 209 tests, fully offline
uv run ruff check .
uv run ruff format --check .
```

**Run all four before claiming a change works.** CI runs exactly these, plus `pytest`
on Python 3.13. `uv run pre-commit install` wires the lint pair into your commits.

The test suite needs **no OCI credentials and no network**. Keep it that way: if a
test needs either, it belongs behind an explicit opt-in environment variable.

## Where to make a change

| Want to… | Edit | Notes |
|---|---|---|
| Add a resource type to `oci_list` / `oci_get` | `registry.py` | One `ResourceKind` entry. Usually the *only* file you need. |
| Change what fields a read returns | `registry.py` (`fields=`) | Not `shaping.py` — that is the generic engine. |
| Change list/sweep/filter behaviour | `reads.py` | Shared by every resource type. |
| Add or change a tool | `tools/read.py`, `server.py` | Registration is conditional; see below. |
| Add a new OCI service client | `clients.py` | Add a `@cache` factory. |

`registry.py` is 498 of the ~1400 source lines and is deliberately a **declarative
table**. Prefer extending the table over adding branches in `reads.py`.

## Invariants — do not "fix" these

Each of these looks like a bug or an oversight and is neither.

**The empty compartment allowlist blocks all mutation.** `OCI_MCP_COMPARTMENTS`
unset means *nothing* may be mutated, not "everything is permitted". A server that
silently allowed tenancy-wide writes when unconfigured would defeat the point of
having an allowlist. `Settings.mutations_possible` encodes this and
`tests/test_config.py` pins it.

**Disabled capabilities are absent, not refusing.** When `OCI_MCP_ALLOW_WRITE` or
`OCI_MCP_ALLOW_DELETE` is false, those tools are never registered in `server.py` — they
do not appear in the catalog at all. A tool a model cannot see is a tool it cannot be
argued into calling. Do not replace this with a runtime check that returns an error.

**Reads dispatch; writes stay explicit.** Reads collapse into three tools because
their schemas are uniform ("show me *type* in *compartment*"). Writes do not share
parameters, so each gets its own tool with a precise schema. **Never add a generic
`oci_create(resource_type, spec)`** — the discriminated-union schema is large and
models fill it in wrong.

**`list_fn` / `get_fn` in the registry are zero-argument lambdas.** They defer building
the service client until first use, so importing the module never needs credentials.
Do not "simplify" them to direct method references; that breaks offline imports and
every test.

**`config.py` imports no OCI SDK.** That is what keeps settings testable without
credentials. Keep OCI imports out of it.

**The ruff version is pinned twice and must match.** `ruff==0.16.7` in
`pyproject.toml` and `rev: v0.16.7` in `.pre-commit-config.yaml`.
`tests/test_tooling.py` fails the build if they drift, because Dependabot can update
one without the other and groups cannot span ecosystems. If you bump one, bump both in
the same change.

## Adding a resource type

The highest-value change and usually one table entry:

```python
"vlan": ResourceKind(
    service="network",
    list_fn=lambda: clients.network().list_vlans,
    get_fn=lambda: clients.network().get_vlan,
    fields=(*_ID, "vcn_id", "cidr=cidr_block", "ad=availability_domain"),
),
```

`fields` entries are `"key"` or `"key=attribute"`; dotted paths reach into nested
models (`"ocpus=shape_config.ocpus"`). A missing attribute yields `None` rather than
raising. Always include a `name` key — a test enforces it.

**Project aggressively.** An OCI `Instance` serialises to 36 fields, mostly null.
Return only what identifies and locates a resource; `verbose=true` gets the full object.

Flags for APIs that break the usual `fn(compartment_id=...)` shape:

| Flag | When |
|---|---|
| `needs_ad=True` | List is availability-domain scoped; the engine fans out across ADs. |
| `needs_namespace=True` | Object Storage; the namespace is injected. |
| `get_by_name=True` | `get` takes a name, not an OCID (buckets). |
| `list_kwargs={...}` | API demands a discriminator, e.g. `{"scope": "REGION"}`. |
| `scope="tenancy"` | Identical in every compartment; query root once. |
| `scope="global"` | No compartment at all (regions). |
| `paginated=False` | Returns everything unpaged and rejects pagination kwargs. |

The tests in `tests/test_registry.py` are parametrised over `REGISTRY`, so a new type
is covered automatically — the test count goes up on its own. Use `note=` for anything
a caller would otherwise get wrong; it is returned with the results.

## Traps specific to this repo

- **Python 3.12 or 3.13 only.** The `oci` SDK does not support 3.14, and
  `requires-python` caps at `<3.14`. The system interpreter may well be newer.
- **Ruff formats Python code blocks inside Markdown.** A fenced `python` block in
  `README.md`, `CONTRIBUTING.md` or this file can fail `ruff format --check`.
- **`fastmcp call` needs `--input-json`,** not `key=value`, when `--command` is used —
  a bare positional is parsed as a server spec and fails with
  `Cannot use both a server spec and --command`. Point it at `--command "uv run oci-mcp"`,
  never at `src/oci_mcp/server.py`, which loads as a script and breaks relative imports.
- **`uv run oci-mcp` appears to hang.** It is a stdio server waiting on stdin. Correct.
- **A stdio server inherits nothing from your shell.** Pass settings via the client's
  env config, or `env VAR=x` inside `--command`.

## OCI behaviour worth knowing

These are Oracle's quirks, already handled in the registry — do not re-derive them:

- **OKE clusters are not indexed by OCI Resource Search.** `oci_search` never returns
  one; `oci_list("cluster")` does.
- **Buckets are addressed by name, not OCID.**
- `list_boot_volume_attachments` requires an availability domain.
- `list_public_ips` requires a `scope`.
- `list_regions` and `list_availability_domains` are unpaginated.
- `list_instances` returns TERMINATED instances unless filtered.
- OKE node names (`oke-<cluster>-<pool>-<rand>-<n>`) embed **truncated OCID suffixes**
  of the real cluster and node pool. Treat them as identifiers, not opaque noise —
  redact them in any screenshot or shared output.

## Style

Match the surrounding code. Specifics that are not obvious from it:

- Comments explain **why**, not what. Several in this codebase record a decision and
  its rejected alternative; that is the intended style.
- Error messages are read by an agent that must recover from them. Say what was wrong
  *and* what the valid options are — `reads.py` and `compartments.py` list valid
  compartments and resource types in their errors. Follow that.
- Line length 100, enforced by ruff.

## Pull requests

- One logical change per PR. Keep formatting-only churn in its own commit.
- Commit messages: short imperative summary, then *why*. The diff says what.
- State how you verified, concretely: "tests went 209 → 213", not "tests pass".
- **Target `main`.** Stacked PRs caused real data loss in this repo: #10 and #11 were
  merged into base branches that had already been squash-merged into `main`, so their
  content was orphaned and had to be recovered in #13.
- Never commit anything derived from a real tenancy — OCIDs, tenancy names, namespaces,
  IPs, OKE node names — in code, tests, fixtures or images.

## Security

This server can read a real cloud account, and will soon be able to change one.

- Never log or return credentials: kubeconfig contents, pre-authenticated request URLs,
  private keys, tokens.
- Never weaken a default so a test passes. If a safety default is inconvenient for a
  test, change the test.
- Mutating code must resolve the target's **own** compartment from the resource and
  check it against the allowlist. Do not trust a caller-supplied compartment argument.
