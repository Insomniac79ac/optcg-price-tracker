import os
from pathlib import Path

# Files/directories that only exist at the repo root, used to walk up to it
# without relying on a hardcoded number of parent directories (which breaks
# as soon as a package is deployed at a different depth, e.g. in Docker).
REPO_ROOT_MARKERS = ("docker-compose.yml", "data", "services")


def find_project_root() -> Path:
    """Best-effort repo root resolution that works in local dev, Docker, and
    pytest, without ever touching `__file__` parent-index arithmetic.

    Resolution order:
      1. The `PROJECT_ROOT` env var, if set.
      2. Walking upward from the current working directory for a directory
         containing all of REPO_ROOT_MARKERS.
      3. The current working directory, if no marker directory is found.
    """
    env_root = os.environ.get("PROJECT_ROOT")
    if env_root:
        return Path(env_root)

    cwd = Path.cwd().resolve()
    for directory in (cwd, *cwd.parents):
        if all((directory / marker).exists() for marker in REPO_ROOT_MARKERS):
            return directory

    return cwd
