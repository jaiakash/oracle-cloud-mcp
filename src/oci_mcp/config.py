"""Environment-derived settings.

Deliberately has no dependency on the OCI SDK so it stays importable (and
testable) without credentials present.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off", ""}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    raise ValueError(
        f"{name}={raw!r} is not a boolean. Use one of: true, false, 1, 0, yes, no."
    )


def _env_tuple(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name, "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved server configuration."""

    profile: str
    region: str | None
    allow_write: bool
    allow_delete: bool
    # Compartment names or OCIDs, exactly as supplied. Resolution to OCIDs needs
    # an authenticated Identity client, so it lives in compartments.py.
    compartment_refs: tuple[str, ...]
    audit_log: str

    @property
    def mutations_possible(self) -> bool:
        """Whether any mutating call could succeed.

        An empty allowlist is a hard stop rather than a wildcard: a server that
        silently permitted writes tenancy-wide when unconfigured would be the
        exact failure mode the allowlist exists to prevent.
        """
        return bool(self.compartment_refs) and (self.allow_write or self.allow_delete)


@cache
def settings() -> Settings:
    return Settings(
        profile=os.environ.get("OCI_CLI_PROFILE", "DEFAULT").strip() or "DEFAULT",
        region=(os.environ.get("OCI_MCP_REGION") or "").strip() or None,
        allow_write=_env_bool("OCI_MCP_ALLOW_WRITE", True),
        allow_delete=_env_bool("OCI_MCP_ALLOW_DELETE", False),
        compartment_refs=_env_tuple("OCI_MCP_COMPARTMENTS"),
        audit_log=os.path.expanduser(
            os.environ.get("OCI_MCP_AUDIT_LOG", "~/.oci-mcp/audit.jsonl")
        ),
    )
