"""Offline tests for settings parsing and the fail-closed mutation rule.

No credentials and no network: config.py deliberately has no OCI SDK dependency.
"""

from __future__ import annotations

import pytest

from oci_mcp.config import Settings, settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    settings.cache_clear()
    yield
    settings.cache_clear()


def _settings(monkeypatch, **env: str) -> Settings:
    for key in (
        "OCI_CLI_PROFILE",
        "OCI_MCP_REGION",
        "OCI_MCP_ALLOW_WRITE",
        "OCI_MCP_ALLOW_DELETE",
        "OCI_MCP_COMPARTMENTS",
        "OCI_MCP_AUDIT_LOG",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return settings()


def test_defaults_are_fail_closed(monkeypatch):
    s = _settings(monkeypatch)
    assert s.profile == "DEFAULT"
    assert s.region is None
    assert s.allow_write is True
    assert s.allow_delete is False
    assert s.compartment_refs == ()
    # Writes are nominally enabled, but with no allowlist nothing can be mutated.
    assert s.mutations_possible is False


def test_empty_allowlist_is_not_a_wildcard(monkeypatch):
    """An unconfigured allowlist must block mutation, never permit it tenancy-wide."""
    s = _settings(monkeypatch, OCI_MCP_ALLOW_WRITE="true", OCI_MCP_ALLOW_DELETE="true")
    assert s.compartment_refs == ()
    assert s.mutations_possible is False


def test_allowlist_enables_mutation(monkeypatch):
    s = _settings(monkeypatch, OCI_MCP_COMPARTMENTS="lab")
    assert s.compartment_refs == ("lab",)
    assert s.mutations_possible is True


def test_allowlist_is_split_and_stripped(monkeypatch):
    s = _settings(monkeypatch, OCI_MCP_COMPARTMENTS=" lab , ocid1.compartment.oc1..xyz ,, ")
    assert s.compartment_refs == ("lab", "ocid1.compartment.oc1..xyz")


def test_both_capabilities_off_blocks_mutation(monkeypatch):
    s = _settings(
        monkeypatch,
        OCI_MCP_COMPARTMENTS="lab",
        OCI_MCP_ALLOW_WRITE="false",
        OCI_MCP_ALLOW_DELETE="false",
    )
    assert s.mutations_possible is False


@pytest.mark.parametrize("raw", ["true", "TRUE", "1", "yes", "on", " True "])
def test_truthy_flags(monkeypatch, raw):
    assert _settings(monkeypatch, OCI_MCP_ALLOW_DELETE=raw).allow_delete is True


@pytest.mark.parametrize("raw", ["false", "FALSE", "0", "no", "off", ""])
def test_falsy_flags(monkeypatch, raw):
    assert _settings(monkeypatch, OCI_MCP_ALLOW_WRITE=raw).allow_write is False


def test_ambiguous_flag_is_rejected_loudly(monkeypatch):
    """A typo'd flag must not silently fall back to a permissive default."""
    with pytest.raises(ValueError, match="not a boolean"):
        _settings(monkeypatch, OCI_MCP_ALLOW_DELETE="maybe")


def test_blank_profile_falls_back_to_default(monkeypatch):
    assert _settings(monkeypatch, OCI_CLI_PROFILE="   ").profile == "DEFAULT"


def test_audit_log_tilde_is_expanded(monkeypatch):
    assert not _settings(monkeypatch).audit_log.startswith("~")
