"""The worker suite carries byte-identical copies of the shared test-support
modules (its image has no services/api to import them from)."""

import pytest

from tests._repo_root import find_repo_root

SHARED = ("pg_url.py", "_source_identity_guard.py")


@pytest.mark.parametrize("name", SHARED)
def test_worker_copy_matches_api_copy(name):
    root = find_repo_root()
    if root is None:
        pytest.skip("Repo root not visible; services/worker is unavailable here.")
    api = root / "services" / "api" / "tests" / name
    worker = root / "services" / "worker" / "tests" / name
    assert worker.read_bytes() == api.read_bytes(), (
        f"{worker} drifted from {api}; copy the api version over it."
    )
