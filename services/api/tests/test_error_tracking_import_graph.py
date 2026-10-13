"""Collector v1 S2 must not be a collector release (PLAN section A, rule 5).

Same tool as the staging delivery continuity check
(scripts/collector_runtime_inputs.py), at the committed HEAD tree: no collector
can reach any API file this session adds or edits, and the files outside
``services/api`` (the API Dockerfile) are outside every collector's path set.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

SESSION_PATHS = [
    "services/api/app/error_tracking.py",
    "services/api/app/main.py",
    "services/api/app/api/admin_observability.py",
    "services/api/requirements-observability.txt",
    "deploy/railway/api.Dockerfile",
]


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


def test_session_files_exist():
    for path in SESSION_PATHS:
        assert (REPO / path).is_file(), path


@pytest.mark.parametrize("collector", ["snkrdunk", "yuyutei"])
def test_no_collector_input_among_session_files(graph, collector):
    tool, inputs = graph
    reached = inputs[collector]
    # The tool really sees the collector graph (models and settings included).
    assert "services/api/app/models/__init__.py" in reached
    assert "services/api/app/settings.py" in reached
    prefixes = tool.full_paths(collector)
    for path in SESSION_PATHS:
        in_path_set = any(path == p or path.startswith(p + "/") for p in prefixes)
        assert not (in_path_set and tool.counts(path, reached)), f"{path} would be a {collector} release"
    assert "services/api/app/error_tracking.py" not in reached
    assert "services/api/app/api/admin_observability.py" not in reached
