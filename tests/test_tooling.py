"""Guard the invariant that local hooks and CI enforce the same ruff.

`.pre-commit-config.yaml` pins the ruff hook to a fixed `rev`, while
`pyproject.toml` pins the ruff package for CI. Nothing structural keeps those two
numbers together: a Dependabot `pre-commit` update bumps only the rev, and a `uv`
update bumps only the package. Either alone produces a tree where pre-commit
passes and CI fails (or vice versa) for the same code.

This test fails on that drift, so the mismatch surfaces in the PR that causes it
rather than in some later contributor's confusing red build.

Deliberately dependency-free: stdlib tomllib plus a regex, so it costs nothing
and cannot itself go stale.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
PRE_COMMIT = ROOT / ".pre-commit-config.yaml"

RUFF_HOOK_REPO = "https://github.com/astral-sh/ruff-pre-commit"


def _pinned_ruff_version() -> str:
    """The exact ruff version pinned in the dev dependency group."""
    data = tomllib.loads(PYPROJECT.read_text())
    dev = data["dependency-groups"]["dev"]
    for entry in dev:
        match = re.fullmatch(r"ruff==([0-9][^\s;]*)", entry.strip())
        if match:
            return match.group(1)
    raise AssertionError(
        f"No exact `ruff==<version>` pin in [dependency-groups].dev: {dev}. "
        "An inexact constraint lets uv drift from the pre-commit hook rev."
    )


def _hook_ruff_rev() -> str:
    """The ruff-pre-commit `rev`, normalised to bare version digits."""
    text = PRE_COMMIT.read_text()
    match = re.search(
        rf"- repo:\s*{re.escape(RUFF_HOOK_REPO)}\s*\n\s*rev:\s*v?([0-9][^\s#]*)",
        text,
    )
    assert match, f"Could not find a {RUFF_HOOK_REPO} rev in {PRE_COMMIT.name}"
    return match.group(1)


def test_ruff_pin_matches_pre_commit_hook_rev():
    pinned = _pinned_ruff_version()
    rev = _hook_ruff_rev()
    assert pinned == rev, (
        f"ruff version drift: pyproject pins ruff=={pinned} but "
        f".pre-commit-config.yaml pins rev v{rev}. "
        "The hooks and CI would enforce different rules. Update both together."
    )


def test_ruff_is_pinned_exactly_not_a_range():
    """A `>=` constraint silently reintroduces the drift this guards against."""
    assert _pinned_ruff_version()  # raises with guidance if inexact


def test_pre_commit_config_is_referenced_by_dev_deps():
    """pre-commit must be installable via `uv sync`, or the documented
    `uv run pre-commit install` fails for a fresh contributor."""
    data = tomllib.loads(PYPROJECT.read_text())
    dev = " ".join(data["dependency-groups"]["dev"])
    assert "pre-commit" in dev, "pre-commit missing from the dev dependency group"
