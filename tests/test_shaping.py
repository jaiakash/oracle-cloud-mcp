"""Offline tests for projections. Uses real SDK model classes, no network."""

from __future__ import annotations

import datetime as dt

import oci

from oci_mcp.shaping import full, project, shape


def _instance(**kw):
    return oci.core.models.Instance(**kw)


def test_rename_and_passthrough():
    i = _instance(display_name="web-1", id="ocid1.instance.x", shape="VM.Standard.E2.1")
    out = project(i, ("name=display_name", "ocid=id", "shape"))
    assert out == {"name": "web-1", "ocid": "ocid1.instance.x", "shape": "VM.Standard.E2.1"}


def test_missing_attribute_is_none_not_error():
    out = project(_instance(), ("name=display_name", "does_not_exist"))
    assert out == {"name": None, "does_not_exist": None}


def test_datetime_becomes_isoformat():
    when = dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc)
    out = project(_instance(time_created=when), ("created=time_created",))
    assert out["created"] == "2026-01-02T03:04:05+00:00"


def test_dotted_path_lifts_one_scalar_from_nested_model():
    i = _instance(
        shape_config=oci.core.models.InstanceShapeConfig(ocpus=4.0, memory_in_gbs=32.0)
    )
    out = project(i, ("ocpus=shape_config.ocpus", "mem=shape_config.memory_in_gbs"))
    assert out == {"ocpus": 4.0, "mem": 32.0}


def test_dotted_path_through_missing_hop_is_none():
    out = project(_instance(), ("ocpus=shape_config.ocpus", "deep=a.b.c.d"))
    assert out == {"ocpus": None, "deep": None}


def test_nested_model_is_flattened_not_stringified():
    """A whole sub-object in a projection must serialise, not become repr()."""
    i = _instance(shape_config=oci.core.models.InstanceShapeConfig(ocpus=1.0))
    out = project(i, ("cfg=shape_config",))
    assert isinstance(out["cfg"], dict)
    assert out["cfg"]["ocpus"] == 1.0


def test_list_of_scalars_passes_through():
    v = oci.core.models.Vcn(cidr_blocks=["10.0.0.0/16", "10.1.0.0/16"])
    assert project(v, ("cidrs=cidr_blocks",))["cidrs"] == ["10.0.0.0/16", "10.1.0.0/16"]


def test_verbose_returns_every_field():
    i = _instance(display_name="x")
    v = shape(i, ("name=display_name",), verbose=True)
    assert v == full(i)
    assert "display_name" in v and len(v) > 20


def test_compact_is_much_smaller_than_verbose():
    """The whole point: a projection must be a fraction of the full object."""
    i = _instance(display_name="x", id="y", lifecycle_state="RUNNING")
    compact = shape(i, ("name=display_name", "ocid=id", "state=lifecycle_state"), verbose=False)
    assert len(compact) == 3
    assert len(full(i)) > 30
