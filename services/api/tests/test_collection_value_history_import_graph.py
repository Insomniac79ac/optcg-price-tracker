"""Collector v1 S4 must not be a collector release (PLAN section A, row S4).

Same import-graph tool as the staging delivery continuity check
(scripts/collector_runtime_inputs.py), at the committed HEAD tree. The S3 test
(test_accounts_import_graph.py) already proves no file under ``app/models/**``,
``app/settings.py`` or API packaging changed against ``origin/staging``; this
adds the daily pipeline, which S4 edits and which lives outside
``app/accounts/``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

S4_PATHS = [
    "services/api/app/market_index_daily_pipeline.py",
    "services/api/app/accounts/value_history.py",
    "services/api/app/accounts/router.py",
    "services/api/app/accounts/schemas.py",
]


@pytest.fixture(scope="module")
def graph():
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git checkout unavailable")
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        import collector_runtime_inputs as tool
    finally:
        sys.path.remove(str(REPO / "scripts"))
    return tool, {name: tool.runtime_inputs(head, name) for name in tool.COLLECTORS}


@pytest.mark.parametrize("collector", ["snkrdunk", "yuyutei"])
def test_no_collector_reaches_the_s4_files(graph, collector):
    tool, inputs = graph
    reached = inputs[collector]
    assert "services/api/app/models/__init__.py" in reached  # the graph is real
    for path in S4_PATHS:
        assert (REPO / path).is_file(), path
        assert path not in reached, f"{collector} imports {path}"
        assert not tool.counts(path, reached), f"{path} would be a {collector} release"
