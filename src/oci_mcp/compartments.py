"""Compartment lookup and allowlist resolution.

Separate from config.py because resolving a compartment *name* to an OCID needs
an authenticated Identity client, and config.py must stay import-safe without
credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from oci.pagination import list_call_get_all_results

from . import clients
from .config import settings


@dataclass(frozen=True, slots=True)
class CompartmentRef:
    name: str
    ocid: str
    is_root: bool = False


class UnknownCompartment(ValueError):
    """Raised when a configured compartment reference cannot be resolved."""


@cache
def all_compartments() -> tuple[CompartmentRef, ...]:
    """Every ACTIVE compartment in the tenancy, root included.

    `list_compartments` does not return the root compartment, so it is prepended
    from the tenancy record.
    """
    root_ocid = clients.tenancy_id()
    tenancy = clients.identity().get_tenancy(root_ocid).data
    found = [CompartmentRef(name=tenancy.name, ocid=root_ocid, is_root=True)]

    response = list_call_get_all_results(
        clients.identity().list_compartments,
        root_ocid,
        compartment_id_in_subtree=True,
        access_level="ANY",
        lifecycle_state="ACTIVE",
    )
    found.extend(
        CompartmentRef(name=c.name, ocid=c.id) for c in response.data
    )
    return tuple(found)


def resolve(ref: str) -> CompartmentRef:
    """Resolve a compartment name or OCID to a CompartmentRef."""
    ref = ref.strip()
    candidates = all_compartments()

    if ref.startswith("ocid1."):
        for c in candidates:
            if c.ocid == ref:
                return c
        raise UnknownCompartment(f"No compartment in this tenancy with OCID {ref}.")

    matches = [c for c in candidates if c.name == ref]
    if not matches:
        names = ", ".join(sorted(c.name for c in candidates))
        raise UnknownCompartment(
            f"No compartment named {ref!r}. Available: {names}."
        )
    if len(matches) > 1:
        # Compartment names are unique only within a parent, so a nested tree can
        # legitimately contain duplicates. Force the caller to disambiguate.
        ocids = ", ".join(c.ocid for c in matches)
        raise UnknownCompartment(
            f"{len(matches)} compartments are named {ref!r}. Use an OCID: {ocids}."
        )
    return matches[0]


def name_for(ocid: str) -> str:
    """Human-readable name for a compartment OCID, falling back to the OCID."""
    for c in all_compartments():
        if c.ocid == ocid:
            return c.name
    return ocid


@cache
def allowlist() -> tuple[CompartmentRef, ...]:
    """Compartments in which mutation is permitted. Empty means none."""
    return tuple(resolve(ref) for ref in settings().compartment_refs)
