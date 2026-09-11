"""Read-only tools. Phase 0 ships orientation only; list/get/search land in Phase 1."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .. import clients, compartments
from ..config import settings


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
            {"name": c.name, "ocid": c.ocid, "is_root": c.is_root}
            for c in compartments.allowlist()
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
