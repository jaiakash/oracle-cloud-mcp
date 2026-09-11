"""Execution engine for the read tools.

Kept separate from tools/read.py so the dispatch logic is testable without an
MCP client, and separate from registry.py so the table stays declarative.

Four irregular call shapes are absorbed here so no caller has to know about them:
  * availability-domain-scoped lists (boot_volume_attachment) -> fan out over ADs
  * Object Storage lists -> inject the tenancy namespace
  * APIs with a mandatory discriminator (public_ip scope) -> static list_kwargs
  * tenancy-wide types (region) -> no compartment at all
"""

from __future__ import annotations

from typing import Any

from oci.exceptions import ServiceError
from oci.pagination import list_call_get_up_to_limit
from oci.resource_search.models import StructuredSearchDetails

from . import clients, compartments, registry, shaping

# Guard against fanning out across an unreasonably large tenancy.
MAX_FANOUT_COMPARTMENTS = 25
# Page size for paginated list calls.
_PAGE = 100


class ReadError(RuntimeError):
    """A read could not be completed; message is safe to show a caller."""


def _targets(
    compartment: str | None, spec: registry.ResourceKind
) -> list[compartments.CompartmentRef]:
    """Which compartments to query. Empty for non-compartment scopes."""
    if spec.scope != "compartment":
        return []

    if compartment:
        try:
            return [compartments.resolve(compartment)]
        except compartments.UnknownCompartment as exc:
            raise ReadError(str(exc)) from None

    everything = list(compartments.all_compartments())
    if len(everything) > MAX_FANOUT_COMPARTMENTS:
        raise ReadError(
            f"This tenancy has {len(everything)} compartments, too many to scan at "
            f"once. Pass `compartment` explicitly, or use oci_search for a "
            f"tenancy-wide query."
        )
    return everything


def _call(spec: registry.ResourceKind, cid: str | None, limit: int) -> list[Any]:
    """One list call, with every irregular argument shape handled."""
    fn = spec.list_fn()
    kwargs: dict[str, Any] = dict(spec.list_kwargs)

    if cid is not None:
        kwargs["compartment_id"] = cid
    if spec.needs_namespace:
        kwargs["namespace_name"] = clients.os_namespace()

    if spec.needs_ad:
        if cid is None:
            return []
        collected: list[Any] = []
        for ad in clients.availability_domains(cid):
            response = list_call_get_up_to_limit(
                fn, limit, _PAGE, availability_domain=ad, **kwargs
            )
            collected.extend(response.data or [])
        return collected

    if not spec.paginated:
        return list(fn(**kwargs).data or [])

    response = list_call_get_up_to_limit(fn, limit, _PAGE, **kwargs)
    return list(response.data or [])


def list_resources(
    resource_type: str,
    compartment: str | None = None,
    limit: int = 50,
    verbose: bool = False,
    lifecycle_state: str | None = None,
) -> dict[str, Any]:
    try:
        spec = registry.kind(resource_type)
    except KeyError as exc:
        raise ReadError(str(exc)) from None

    if limit < 1:
        raise ReadError("limit must be at least 1.")

    targets = _targets(compartment, spec)
    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    # Fetch one past the limit so truncation is detectable, and over-fetch
    # further when a client-side state filter will discard some rows.
    want = limit + 1
    per_call = want if lifecycle_state is None else want * 4

    def absorb(records: list[Any], where: compartments.CompartmentRef | None) -> None:
        for record in records:
            row = shaping.shape(record, spec.fields, verbose)
            if where is not None and not verbose:
                row["compartment"] = where.name
            items.append(row)

    if spec.scope == "global":
        absorb(_call(spec, None, per_call), None)
    elif spec.scope == "tenancy":
        absorb(_call(spec, clients.tenancy_id(), per_call), None)
    else:
        for ref in targets:
            try:
                absorb(_call(spec, ref.ocid, per_call), ref)
            except ServiceError as exc:
                # A compartment the caller cannot read must not fail the whole
                # sweep: report it alongside the results that did come back.
                errors.append({
                    "compartment": ref.name,
                    "status": str(exc.status),
                    "message": exc.message,
                })
            # Stop sweeping once we know the answer is truncated. Not safe
            # when a state filter is pending: we cannot know the kept count yet.
            if lifecycle_state is None and len(items) > limit:
                break

    if lifecycle_state:
        wanted = lifecycle_state.upper()
        items = [i for i in items if str(i.get("state", "")).upper() == wanted]

    truncated = len(items) > limit
    result: dict[str, Any] = {
        "resource_type": resource_type,
        "service": spec.service,
        "count": min(len(items), limit),
        "items": items[:limit],
    }
    if truncated:
        result["truncated"] = True
        result["hint"] = f"More than {limit} matched; raise `limit` or narrow `compartment`."
    if compartment is None and spec.scope == "compartment":
        result["scanned_compartments"] = [t.name for t in targets]
    if errors:
        result["inaccessible_compartments"] = errors
    if spec.note:
        result["note"] = spec.note
    return result


def get_resource(resource_type: str, target: str, verbose: bool = True) -> dict[str, Any]:
    try:
        spec = registry.kind(resource_type)
    except KeyError as exc:
        raise ReadError(str(exc)) from None

    if spec.get_fn is None:
        raise ReadError(
            f"{resource_type!r} has no get operation. "
            f"Use oci_list('{resource_type}') and filter the results."
        )

    fn = spec.get_fn()
    try:
        if spec.get_by_name:
            record = fn(clients.os_namespace(), target).data
        else:
            record = fn(target).data
    except ServiceError as exc:
        if exc.status == 404:
            hint = (
                f"No {resource_type} named {target!r} found."
                if spec.get_by_name
                else f"No {resource_type} with OCID {target!r} found in region "
                     f"{clients.region()}."
            )
            raise ReadError(hint) from None
        raise ReadError(f"OCI returned {exc.status}: {exc.message}") from None

    detail = shaping.shape(record, spec.fields, verbose)
    return {"resource_type": resource_type, "service": spec.service, "detail": detail}


def search(
    query: str | None = None, free_text: str | None = None, limit: int = 50
) -> dict[str, Any]:
    if not query and not free_text:
        raise ReadError("Provide either `query` (structured) or `free_text`.")
    if query and free_text:
        raise ReadError("Provide only one of `query` or `free_text`.")

    if query:
        details: Any = StructuredSearchDetails(
            query=query,
            matching_context_type=StructuredSearchDetails.MATCHING_CONTEXT_TYPE_NONE,
        )
    else:
        from oci.resource_search.models import FreeTextSearchDetails

        details = FreeTextSearchDetails(
            text=free_text,
            matching_context_type=FreeTextSearchDetails.MATCHING_CONTEXT_TYPE_NONE,
        )

    try:
        response = clients.search().search_resources(details, limit=min(limit, 1000))
    except ServiceError as exc:
        raise ReadError(
            f"Search failed with {exc.status}: {exc.message}. "
            "Structured queries look like: "
            "query instance resources where lifecycleState = 'RUNNING'"
        ) from None

    items = [
        {
            "name": r.display_name,
            "ocid": r.identifier,
            "type": r.resource_type,
            "state": r.lifecycle_state,
            "compartment": compartments.name_for(r.compartment_id),
            "created": r.time_created.isoformat() if r.time_created else None,
        }
        for r in (response.data.items or [])
    ]
    return {
        "count": len(items),
        "items": items,
        "note": "Resource Search does not index every service; OKE clusters in "
                "particular never appear here. Use oci_list('cluster') for those.",
    }
