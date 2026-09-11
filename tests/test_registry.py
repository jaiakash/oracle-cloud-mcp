"""Structural checks on the resource table. No network, no credentials.

The lambdas are deliberately NOT invoked here: doing so builds service clients,
which needs ~/.oci/config. test_live.py covers that path.
"""

from __future__ import annotations

import re

import pytest

from oci_mcp.registry import REGISTRY, RESOURCE_TYPES, ResourceKind, by_service, kind

KNOWN_SERVICES = {
    "compute", "block_storage", "network", "oke", "database", "object_storage", "identity",
}


def test_resource_types_mirror_registry_keys():
    assert RESOURCE_TYPES == tuple(REGISTRY)


@pytest.mark.parametrize("name", RESOURCE_TYPES)
def test_type_name_is_snake_case(name):
    assert re.fullmatch(r"[a-z][a-z0-9_]*", name), name


@pytest.mark.parametrize("name,spec", REGISTRY.items())
def test_entry_is_well_formed(name, spec: ResourceKind):
    assert spec.service in KNOWN_SERVICES, f"{name}: unknown service {spec.service}"
    assert callable(spec.list_fn), f"{name}: list_fn must be a zero-arg callable"
    assert spec.get_fn is None or callable(spec.get_fn)
    assert spec.scope in {"compartment", "tenancy", "global"}, name
    assert spec.fields, f"{name}: empty projection"


@pytest.mark.parametrize("name,spec", REGISTRY.items())
def test_every_projection_names_the_resource(name, spec: ResourceKind):
    keys = {f.partition("=")[0] for f in spec.fields}
    assert "name" in keys, f"{name}: projection has no 'name' key"


@pytest.mark.parametrize("name,spec", REGISTRY.items())
def test_field_specs_are_well_formed(name, spec: ResourceKind):
    for f in spec.fields:
        key, sep, attr = f.partition("=")
        assert key and re.fullmatch(r"[a-z][a-z0-9_]*", key), f"{name}: bad key in {f!r}"
        if sep:
            assert re.fullmatch(r"[a-z_][a-z0-9_.]*", attr), f"{name}: bad attribute in {f!r}"


def test_get_by_name_only_for_object_storage():
    by_name = {n for n, s in REGISTRY.items() if s.get_by_name}
    assert by_name == {"bucket"}


def test_ad_fanout_types_are_compartment_scoped():
    for n, s in REGISTRY.items():
        if s.needs_ad:
            assert s.scope == "compartment", n


def test_non_compartment_scopes_are_unpaginated_single_calls():
    """tenancy/global scopes exist for APIs that return everything at once."""
    for n, s in REGISTRY.items():
        if s.scope != "compartment":
            assert not s.paginated, n
            assert not s.needs_ad, n


def test_by_service_covers_everything_once():
    grouped = by_service()
    flat = [t for names in grouped.values() for t in names]
    assert sorted(flat) == sorted(RESOURCE_TYPES)
    assert set(grouped) == KNOWN_SERVICES


def test_unknown_type_error_lists_valid_types():
    with pytest.raises(KeyError) as exc:
        kind("nope")
    msg = str(exc.value)
    assert "nope" in msg
    assert "instance" in msg and "bucket" in msg


def test_phase_one_coverage():
    """The types the user asked for by name must all be present."""
    for wanted in ("instance", "cluster", "node_pool", "volume", "boot_volume",
                   "autonomous_database", "db_system", "mysql_db_system"):
        assert wanted in REGISTRY
