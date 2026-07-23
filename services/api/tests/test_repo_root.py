"""Regression coverage for tests/_repo_root.py's find_repo_root - the helper
that replaced test_phase9_audit_script.py/test_release_candidate_audit_script.py's
old `Path(__file__).resolve().parents[3]`, which raised IndexError as soon as
those tests ran inside the api Docker image (only services/api is copied to
/app there, so the parent chain is shallower than a dev checkout) - see
docs/release_blockers.md RC-1.

Uses scaffolded tmp_path directories throughout (mirroring
services/worker/tests/test_path_utils.py's find_project_root tests) rather
than asserting anything about _repo_root.py's own real location, since that
location's ancestor chain legitimately differs between a full checkout and
the api container's shallower layout - a test that assumed one or the other
would be exactly the kind of environment-dependent flakiness RC-1 was about.
"""

from pathlib import Path

from tests._repo_root import find_repo_root


def test_find_repo_root_prefers_project_root_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    assert find_repo_root(start=tmp_path / "unused") == tmp_path


def test_find_repo_root_walks_up_for_repo_markers(monkeypatch, tmp_path):
    monkeypatch.delenv("PROJECT_ROOT", raising=False)

    repo_root = tmp_path / "repo"
    (repo_root / "scripts").mkdir(parents=True)
    (repo_root / "services").mkdir()
    (repo_root / "docker-compose.yml").write_text("")

    nested_start = repo_root / "services" / "api" / "tests" / "_repo_root.py"
    nested_start.parent.mkdir(parents=True)

    assert find_repo_root(start=nested_start) == repo_root


def test_find_repo_root_returns_none_when_no_markers_are_visible(monkeypatch, tmp_path):
    monkeypatch.delenv("PROJECT_ROOT", raising=False)

    # Mirrors the api Docker image's actual shallow layout: no ancestor
    # directory has scripts/ + services/ + docker-compose.yml all present.
    isolated = tmp_path / "app" / "tests" / "_repo_root.py"
    isolated.parent.mkdir(parents=True)

    assert find_repo_root(start=isolated) is None


def test_find_repo_root_defaults_to_its_own_file_location():
    # No start= override - exercises the real default path, whatever it
    # resolves to in this environment (a full checkout or the api
    # container). Only checks the function runs and returns the right type,
    # not which outcome it lands on - that's exactly the thing the two tests
    # above pin down deterministically.
    result = find_repo_root()
    assert result is None or isinstance(result, Path)
