"""Turn verbose OCI models into compact dicts.

An OCI `Instance` serialises to 36 fields, most of them null. Returning a handful
of those raw would exhaust an agent's context for no benefit, so every read is
projected down to the fields that identify and locate a resource. `verbose=True`
escapes to the full object when the detail is genuinely wanted.

Projections are declared as field specs on each ResourceKind (see registry.py)
rather than as one function per resource type, so adding a type is one line.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from oci.util import to_dict

# Field specs are "key=attribute" or just "attribute" when the two match.
FieldSpec = tuple[str, ...]


def _scalar(value: Any) -> Any:
    """Reduce an SDK attribute to something JSON-friendly and compact."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_scalar(v) for v in value]
    if isinstance(value, dict):
        return {k: _scalar(v) for k, v in value.items()}
    # A nested SDK model: flatten rather than recurse, so a projection can never
    # blow up into the full object graph it exists to avoid.
    if hasattr(value, "swagger_types"):
        return to_dict(value)
    return str(value)


def _walk(obj: Any, path: str) -> Any:
    """Resolve a dotted attribute path, yielding None if any hop is missing.

    Lets a projection reach into a nested model (shape_config.ocpus) to lift one
    useful scalar out, instead of embedding the whole sub-object.
    """
    current = obj
    for part in path.split("."):
        if current is None:
            return None
        current = getattr(current, part, None)
    return current


def project(obj: Any, fields: FieldSpec) -> dict[str, Any]:
    """Extract `fields` from an SDK model into a flat dict.

    Missing attributes yield None rather than raising: the same spec is reused
    across API versions and across resources that only sometimes carry a field.
    """
    out: dict[str, Any] = {}
    for spec in fields:
        key, sep, attr = spec.partition("=")
        source = attr if sep else key
        out[key] = _scalar(_walk(obj, source))
    return out


def full(obj: Any) -> dict[str, Any]:
    """Every field of an SDK model, for verbose reads."""
    return to_dict(obj)


def shape(obj: Any, fields: FieldSpec, verbose: bool) -> dict[str, Any]:
    return full(obj) if verbose else project(obj, fields)
