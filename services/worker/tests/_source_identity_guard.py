"""Session-start guard: the imported opcg_source_identity must be this
checkout's packages/opcg_source_identity.

Every worktree shares one virtualenv, so a site-packages copy installed from
another worktree (or an older commit) silently answers `import
opcg_source_identity` with different code. CI installs the package
non-editable from its own checkout, so the installed directory legitimately
lives in site-packages; what must match is the code, not the path. The guard
therefore compares the sha256 of every .py file in the imported package
directory against packages/opcg_source_identity/src/opcg_source_identity,
resolved relative to the calling conftest. An editable install or PYTHONPATH
pointing at the checkout source matches trivially.

When the checkout source is not visible (e.g. a service image that only
copies services/<name>), there is nothing to compare against and the guard
is a no-op.

services/worker/tests/_source_identity_guard.py is a byte-identical copy;
services/api/tests/test_pg_url_parity.py keeps the two in step.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

PACKAGE = "opcg_source_identity"
FIX = "python -m pip install --no-deps ./packages/opcg_source_identity"


def _digests(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*.py"))
    }


def check_source_identity_package(tests_dir: Path) -> None:
    """Raise pytest.UsageError unless the importable opcg_source_identity is
    byte-identical to the checkout that `tests_dir` (services/<svc>/tests)
    belongs to."""
    repo_root = tests_dir.resolve().parents[2]
    checkout = repo_root / "packages" / PACKAGE / "src" / PACKAGE
    if not checkout.is_dir():
        return

    spec = importlib.util.find_spec(PACKAGE)
    if spec is None or not spec.submodule_search_locations:
        raise pytest.UsageError(
            f"{PACKAGE} is not importable; this checkout's copy is {checkout}.\n"
            f"Fix (from {repo_root}): {FIX}  (or: pip install --no-deps -e ./packages/{PACKAGE})"
        )
    installed = Path(next(iter(spec.submodule_search_locations))).resolve()
    if installed == checkout.resolve():
        return

    have, want = _digests(installed), _digests(checkout)
    if have == want:
        return
    missing = sorted(want.keys() - have.keys())
    extra = sorted(have.keys() - want.keys())
    changed = sorted(name for name in want.keys() & have.keys() if want[name] != have[name])
    raise pytest.UsageError(
        f"Imported {PACKAGE} is not this checkout's copy.\n"
        f"  imported from: {installed}\n"
        f"  checkout copy: {checkout}\n"
        f"  missing={missing} extra={extra} changed={changed}\n"
        f"Likely a stale install from another worktree in a shared virtualenv.\n"
        f"Fix (from {repo_root}): {FIX}  (or: pip install --no-deps -e ./packages/{PACKAGE})"
    )
