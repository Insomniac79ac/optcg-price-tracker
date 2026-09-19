"""Test-only discovery for optional repository-level fixtures.

The worker is deployed as a standalone service, so its tests must tolerate
the repository root being absent (for example when only services/worker is
copied to /app).  Callers decide whether an absent optional fixture should
skip; this helper only discovers a visible checkout without relying on cwd or
a fixed number of parent directories.
"""

from pathlib import Path

REPO_ROOT_MARKERS = ("docker-compose.yml", "services")


def find_repo_root(start: Path | None = None) -> Path | None:
    here = (start if start is not None else Path(__file__)).resolve()
    for directory in (here, *here.parents):
        if all((directory / marker).exists() for marker in REPO_ROOT_MARKERS):
            return directory
    return None
