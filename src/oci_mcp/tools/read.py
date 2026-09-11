"""Read-only tools. Phase 0 ships orientation only; list/get/search land in Phase 1."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .. import clients, compartments, reads, registry
from ..config import settings

# Generated from the registry so the tool schema always advertises exactly the
# types that are actually dispatchable, and the two can never drift.
ResourceType = StrEnum("ResourceType", {t: t for t in registry.RESOURCE_TYPES})


def _identity_summary() -> dict[str, Any]:
    cfg = clients.config()
    tenancy = clients.identity().get_tenancy(cfg["tenancy"]).data

    user: dict[str, Any]
    user_ocid = cfg.get("user")
    if user_ocid:
        record = clients.identity().get_user(user_ocid).data
        user = {"name": record.name, "ocid": record.id, "description": record.description}
    else:
        # Session-token and principal-based auth carry no user OCID in config.
        user = {"name": None, "ocid": None, "description": "not available for this auth method"}

    return {
        "tenancy": {"name": tenancy.name, "ocid": tenancy.id},
        "user": user,
        "region": cfg["region"],
        "home_region_key": tenancy.home_region_key,
    }


def _permissions_summary() -> dict[str, Any]:
    s = settings()
    try:
        allowed = [
            {"name": c.name, "ocid": c.ocid, "is_root": c.is_root} for c in compartments.allowlist()
        ]
        allowlist_error = None
    except compartments.UnknownCompartment as exc:
        allowed = []
        allowlist_error = str(exc)

    notes = []
    if not s.compartment_refs:
        notes.append(
            "OCI_MCP_COMPARTMENTS is empty, so no mutating call can succeed. "
            "Set it to a disposable compartment to enable writes."
        )
    if allowlist_error:
        notes.append(f"Allowlist could not be resolved: {allowlist_error}")
    if not s.allow_write:
        notes.append("OCI_MCP_ALLOW_WRITE is false: write tools are not registered.")
    if not s.allow_delete:
        notes.append("OCI_MCP_ALLOW_DELETE is false: delete tools are not registered.")

    return {
        "allow_write": s.allow_write,
        "allow_delete": s.allow_delete,
        "mutations_possible": s.mutations_possible,
        "mutable_compartments": allowed,
        "notes": notes,
    }


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations={
            "title": "Who am I on OCI",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    def oci_whoami() -> dict[str, Any]:
        """Report the active OCI identity and this server's own permissions.

        Returns the tenancy, user, region and auth method in use, plus which
        compartments may be mutated and which capability flags are enabled.

        Call this first in a session to learn what is reachable before acting.
        """
        try:
            return {
                "profile": settings().profile,
                "auth_method": clients.auth_method(),
                **_identity_summary(),
                "permissions": _permissions_summary(),
                "compartments_visible": len(compartments.all_compartments()),
            }
        except clients.ConfigError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool(
        annotations={
            "title": "List OCI resources",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    def oci_list(
        resource_type: ResourceType,
        compartment: Annotated[
            str | None,
            "Compartment name or OCID. Omit to scan every compartment in the tenancy.",
        ] = None,
        limit: Annotated[int, "Maximum rows to return."] = 50,
        lifecycle_state: Annotated[
            str | None,
            "Filter by state, e.g. RUNNING, AVAILABLE, ACTIVE, TERMINATED.",
        ] = None,
        verbose: Annotated[bool, "Return every field instead of the compact projection."] = False,
    ) -> dict[str, Any]:
        """List resources of one type, compactly.

        Covers compute, block storage, networking, OKE, database, object storage
        and identity. Results are projected to the identifying fields; pass
        verbose=True for the full objects.

        Omitting `compartment` scans the whole tenancy and tags each row with the
        compartment it came from.
        """
        try:
            return reads.list_resources(
                resource_type=str(resource_type),
                compartment=compartment,
                limit=limit,
                verbose=verbose,
                lifecycle_state=lifecycle_state,
            )
        except (reads.ReadError, clients.ConfigError) as exc:
            raise ToolError(str(exc)) from None

    @mcp.tool(
        annotations={
            "title": "Get one OCI resource",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    def oci_get(
        resource_type: ResourceType,
        target: Annotated[
            str,
            "The resource OCID. For resource_type='bucket' pass the bucket NAME instead.",
        ],
        verbose: Annotated[
            bool, "Full detail (default). Set false for the compact projection."
        ] = True,
    ) -> dict[str, Any]:
        """Fetch full details for a single resource.

        Use this after oci_list or oci_search has given you an OCID and you need
        the complete record — configuration, nested settings, tags.
        """
        try:
            return reads.get_resource(
                resource_type=str(resource_type), target=target, verbose=verbose
            )
        except (reads.ReadError, clients.ConfigError) as exc:
            raise ToolError(str(exc)) from None

    @mcp.tool(
        annotations={
            "title": "Search OCI resources",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    def oci_search(
        query: Annotated[
            str | None,
            "Structured query, e.g. \"query instance resources where lifecycleState = 'RUNNING'\". "
            "Use 'all' in place of a type to search every resource type.",
        ] = None,
        free_text: Annotated[
            str | None, "Plain-text search over names and tags. Mutually exclusive with query."
        ] = None,
        limit: Annotated[int, "Maximum rows to return."] = 50,
    ) -> dict[str, Any]:
        """Find resources of any type across the whole tenancy in one call.

        The fastest way to locate something when you do not know its compartment.
        Prefer this over sweeping oci_list across many types.

        Examples:
          query="query all resources where lifecycleState = 'RUNNING'"
          query="query instance, volume resources where displayName =~ 'test'"
          free_text="kubeflow"

        Note: Resource Search does not index every service. OKE clusters never
        appear; use oci_list('cluster') for those.
        """
        try:
            return reads.search(query=query, free_text=free_text, limit=limit)
        except (reads.ReadError, clients.ConfigError) as exc:
            raise ToolError(str(exc)) from None
