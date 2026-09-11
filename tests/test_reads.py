"""Offline tests for the read engine, using a fake ResourceKind injected into the
registry and stubbed compartment lookups. No network."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from oci.exceptions import ServiceError

from oci_mcp import compartments, reads, registry
from oci_mcp.compartments import CompartmentRef

LAB = CompartmentRef(name="lab", ocid="ocid1.compartment.lab")
PROD = CompartmentRef(name="prod", ocid="ocid1.compartment.prod")


def _rec(name, state="RUNNING"):
    return SimpleNamespace(display_name=name, id=f"ocid1.thing.{name}", lifecycle_state=state)


def _fake_kind(list_impl, **overrides):
    """A paginated=False kind so list_fn is called plainly as fn(**kwargs)."""
    return registry.ResourceKind(
        service="compute",
        list_fn=lambda: list_impl,
        fields=("name=display_name", "ocid=id", "state=lifecycle_state"),
        paginated=False,
        **overrides,
    )


@pytest.fixture
def two_compartments(monkeypatch):
    monkeypatch.setattr(compartments, "all_compartments", lambda: (LAB, PROD))

    def resolve(ref):
        for c in (LAB, PROD):
            if ref in (c.name, c.ocid):
                return c
        raise compartments.UnknownCompartment(f"No compartment named {ref!r}.")

    monkeypatch.setattr(compartments, "resolve", resolve)


@pytest.fixture
def fake_type(monkeypatch, two_compartments):
    """Register 'thing' whose rows depend on which compartment is asked."""
    data = {
        LAB.ocid: [_rec("a"), _rec("b", "STOPPED")],
        PROD.ocid: [_rec("c")],
    }

    def list_things(compartment_id, **_):
        return SimpleNamespace(data=data[compartment_id])

    monkeypatch.setitem(registry.REGISTRY, "thing", _fake_kind(list_things))
    return "thing"


def test_fanout_tags_rows_with_compartment(fake_type):
    r = reads.list_resources(fake_type)
    assert r["count"] == 3
    assert {(i["name"], i["compartment"]) for i in r["items"]} == {
        ("a", "lab"), ("b", "lab"), ("c", "prod")
    }
    assert r["scanned_compartments"] == ["lab", "prod"]


def test_explicit_compartment_restricts_scan(fake_type):
    r = reads.list_resources(fake_type, compartment="prod")
    assert [i["name"] for i in r["items"]] == ["c"]
    assert "scanned_compartments" not in r


def test_unknown_compartment_is_a_read_error(fake_type):
    with pytest.raises(reads.ReadError, match="No compartment named"):
        reads.list_resources(fake_type, compartment="nope")


def test_lifecycle_filter_is_case_insensitive(fake_type):
    r = reads.list_resources(fake_type, lifecycle_state="stopped")
    assert [i["name"] for i in r["items"]] == ["b"]


def test_truncation_is_reported(fake_type):
    r = reads.list_resources(fake_type, limit=2)
    assert r["count"] == 2 and r["truncated"] is True
    assert "limit" in r["hint"]


def test_one_forbidden_compartment_does_not_sink_the_sweep(monkeypatch, two_compartments):
    def list_things(compartment_id, **_):
        if compartment_id == PROD.ocid:
            raise ServiceError(404, "NotAuthorizedOrNotFound", {}, "nope")
        return SimpleNamespace(data=[_rec("a")])

    monkeypatch.setitem(registry.REGISTRY, "thing", _fake_kind(list_things))
    r = reads.list_resources("thing")
    assert [i["name"] for i in r["items"]] == ["a"]
    assert r["inaccessible_compartments"] == [
        {"compartment": "prod", "status": "404", "message": "nope"}
    ]


def test_global_scope_makes_one_call_without_compartment(monkeypatch, two_compartments):
    calls = []

    def list_regions(**kw):
        calls.append(kw)
        return SimpleNamespace(data=[SimpleNamespace(display_name="r1", id="x", lifecycle_state=None)])

    monkeypatch.setitem(registry.REGISTRY, "thing", _fake_kind(list_regions, scope="global"))
    r = reads.list_resources("thing")
    assert calls == [{}]
    assert r["count"] == 1 and "compartment" not in r["items"][0]


def test_tenancy_scope_calls_root_once(monkeypatch, two_compartments):
    monkeypatch.setattr(reads.clients, "tenancy_id", lambda: "ocid1.tenancy.root")
    calls = []

    def list_ads(**kw):
        calls.append(kw)
        return SimpleNamespace(data=[_rec("AD-1")])

    monkeypatch.setitem(registry.REGISTRY, "thing", _fake_kind(list_ads, scope="tenancy"))
    reads.list_resources("thing")
    assert calls == [{"compartment_id": "ocid1.tenancy.root"}]


def test_static_list_kwargs_are_forwarded(monkeypatch, two_compartments):
    seen = []

    def list_ips(**kw):
        seen.append(kw.get("scope"))
        return SimpleNamespace(data=[])

    monkeypatch.setitem(
        registry.REGISTRY, "thing", _fake_kind(list_ips, list_kwargs={"scope": "REGION"})
    )
    reads.list_resources("thing")
    assert seen == ["REGION", "REGION"]


def test_unknown_type_lists_valid_ones():
    with pytest.raises(reads.ReadError, match="instance"):
        reads.list_resources("nope")


def test_limit_must_be_positive(fake_type):
    with pytest.raises(reads.ReadError, match="at least 1"):
        reads.list_resources(fake_type, limit=0)


def test_get_on_type_without_get_is_explained(monkeypatch, two_compartments):
    monkeypatch.setitem(registry.REGISTRY, "thing", _fake_kind(lambda **_: None))
    with pytest.raises(reads.ReadError, match="no get operation"):
        reads.get_resource("thing", "ocid1.x")


def test_get_404_gives_targeted_hint(monkeypatch, two_compartments):
    monkeypatch.setattr(reads.clients, "region", lambda: "us-ashburn-1")

    def get_thing(_id):
        raise ServiceError(404, "NotFound", {}, "gone")

    monkeypatch.setitem(
        registry.REGISTRY, "thing", _fake_kind(lambda **_: None, get_fn=lambda: get_thing)
    )
    with pytest.raises(reads.ReadError, match="us-ashburn-1"):
        reads.get_resource("thing", "ocid1.missing")


def test_search_requires_exactly_one_mode():
    with pytest.raises(reads.ReadError, match="either"):
        reads.search()
    with pytest.raises(reads.ReadError, match="only one"):
        reads.search(query="q", free_text="t")
