"""Best-effort repo-root resolution for tests that check root-level artifacts
(scripts/, docs/) which only exist in a full dev checkout - not inside the api
Docker image, which only copies services/api to /app (mirrors
services/worker/worker/path_utils.py's find_project_root, which solved the
same problem for the worker image)."""

import os
from pathlib import Path

REPO_ROOT_MARKERS = ("docker-compose.yml", "scripts", "services")


def find_repo_root(start: Path | None = None) -> Path | None:
    """Returns the repo root if this process can see it, else None (e.g. when
    running inside the api container, which only has services/api copied
    in - callers should skip rather than fail in that case).

    `start` defaults to this file's own location - overridable so tests can
    point it at a scaffolded directory instead of depending on where
    _repo_root.py physically lives on disk (which varies between a full
    checkout and the api container's shallower layout)."""
    env_root = os.environ.get("PROJECT_ROOT")
    if env_root:
        return Path(env_root)

    here = (start if start is not None else Path(__file__)).resolve()
    for directory in (here, *here.parents):
        if all((directory / marker).exists() for marker in REPO_ROOT_MARKERS):
            return directory

    return None
