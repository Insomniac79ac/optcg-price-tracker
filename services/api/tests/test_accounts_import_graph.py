"""Collector v1 S3 must not be a collector release (PLAN section A).

Uses the same import-graph tool the staging delivery continuity check uses
(scripts/collector_runtime_inputs.py), at the committed HEAD tree. It proves:

* no collector can reach any module of ``app/accounts/`` or any other file this
  session adds or edits, so ``counts()`` is false for each of them;
* none of the files whose change is always a collector input (``app/models/**``,
  ``app/settings.py``, API packaging and requirements) is changed relative to
  the merge base with ``origin/staging`` when that ref is available.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
API = REPO / "services" / "api"

# Every path this session adds or edits under services/api (besides tests).
SESSION_PATHS = [
    "services/api/app/main.py",
    "services/api/alembic/env.py",
    "services/api/alembic/versions/3b7d9c1a5e20_add_collector_account_tables.py",
    *sorted(
        str(path.relative_to(REPO))
        for path in (API / "app" / "accounts").glob("*.py")
    ),
]
FORBIDDEN_PREFIXES = ("services/api/app/models/",)
FORBIDDEN_FILES = {
    "services/api/app/settings.py",
    "services/api/app/db.py",
    "services/api/app/env.py",
    "services/api/requirements.txt",
    "services/api/pyproject.toml",
    "services/api/setup.py",
    "services/api/setup.cfg",
    "services/api/MANIFEST.in",
}


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


@pytest.fixture(scope="module")
def graph():
    try:
        head = _git("rev-parse", "HEAD")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git checkout unavailable")
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        import collector_runtime_inputs as tool
    finally:
        sys.path.remove(str(REPO / "scripts"))
    return tool, {name: tool.runtime_inputs(head, name) for name in tool.COLLECTORS}


def test_session_files_are_known():
    assert len(SESSION_PATHS) >= 9, SESSION_PATHS
    for path in SESSION_PATHS:
        assert (REPO / path).is_file(), path


@pytest.mark.parametrize("collector", ["snkrdunk", "yuyutei"])
def test_no_collector_reaches_any_session_file(graph, collector):
    tool, inputs = graph
    reached = inputs[collector]
    # The tool really sees the collector graph (models and settings included).
    assert "services/api/app/models/__init__.py" in reached
    assert "services/api/app/settings.py" in reached
    assert not [p for p in reached if p.startswith("services/api/app/accounts/")]
    for path in SESSION_PATHS:
        assert not tool.counts(path, reached), f"{path} would be a {collector} release"


def test_no_always_collector_input_changed_against_staging():
    try:
        base = _git("merge-base", "HEAD", "origin/staging")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("origin/staging not available in this checkout")
    changed = set(_git("diff", "--name-only", base, "--", "services/api").split())
    changed |= set(_git("diff", "--name-only", "--", "services/api").split())
    offenders = sorted(
        path
        for path in changed
        if path in FORBIDDEN_FILES or path.startswith(FORBIDDEN_PREFIXES)
        or (path.startswith("services/api/app/") and not path.endswith(".py"))
    )
    assert offenders == []


def test_accounts_package_is_not_imported_by_shared_modules():
    """Nothing in app.models, app.settings or app.services imports the package."""
    for folder in ("models", "services"):
        for path in (API / "app" / folder).rglob("*.py"):
            assert "app.accounts" not in path.read_text(), path
    assert "app.accounts" not in (API / "app" / "settings.py").read_text()
