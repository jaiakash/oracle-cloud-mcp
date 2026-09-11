## What changed

<!-- One or two sentences. The diff says what; say why. -->

## Why

<!-- The problem this solves. Link the issue: Closes #123 -->

## How it was verified

<!--
Be concrete. For example:
  uv run pytest -q          -> 210 passed (was 206; the new type is auto-covered)
  uv run ruff check .       -> All checks passed
  listed it against a real tenancy -> 3 rows
Say so if you could not test something, and why.
-->

## Checklist

- [ ] `uv run pytest -q` passes
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] One logical change (formatting kept in its own commit)
- [ ] Docs updated if behaviour or configuration changed
