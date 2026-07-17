"""App/build version metadata - see GET /version, GET /health, and GET
/admin/release-status (docs/release_checklist.md).

APP_VERSION/GIT_COMMIT/BUILD_TIME are baked in as env vars at Docker build
time (see services/api/Dockerfile and the Makefile's prod-build target), so
they always win when set. The VERSION file is the fallback for anywhere
those env vars aren't set - a bare `uvicorn`/pytest run from the repo
checkout (services/api's own Dockerfile only copies services/api into the
image, so the repo-root VERSION file isn't present in a built image; the
build-arg env var is what carries it in there instead).
"""

from __future__ import annotations

import os
from pathlib import Path

from app.env import get_app_env

APP_NAME = "opcg-price-tracker"
UNKNOWN = "unknown"
FALLBACK_VERSION = "0.0.0-unknown"

# Search cwd first, then walk up from this file's own location - covers both
# "run from repo root" and "run from services/api" without hardcoding a
# specific number of parent directories.
_SEARCH_ROOTS = [Path.cwd(), *Path(__file__).resolve().parents]


def _read_version_file() -> str | None:
    for root in _SEARCH_ROOTS:
        candidate = root / "VERSION"
        if not candidate.is_file():
            continue
        try:
            content = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if content:
            return content
    return None


def get_version() -> str:
    return os.environ.get("APP_VERSION") or _read_version_file() or FALLBACK_VERSION


def get_git_commit() -> str:
    return os.environ.get("GIT_COMMIT") or UNKNOWN


def get_build_time() -> str:
    return os.environ.get("BUILD_TIME") or UNKNOWN


def get_version_info() -> dict[str, str]:
    return {
        "app": APP_NAME,
        "version": get_version(),
        "git_commit": get_git_commit(),
        "build_time": get_build_time(),
        "app_env": get_app_env(),
    }
