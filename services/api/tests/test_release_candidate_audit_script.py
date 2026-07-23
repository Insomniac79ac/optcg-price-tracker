"""Sanity checks that scripts/release_candidate_audit.sh (the Phase 11
release-candidate audit) exists, is executable, and that scripts/final_audit.sh
knows about it - mirrors services/api/tests/test_phase9_audit_script.py for
the phase 7/8/9 audit scripts. Does not actually run the script (it needs a
live docker compose stack, and its own test suites are what's being run) -
see docs/release_candidate_report.md."""

import os

import pytest

from tests._repo_root import find_repo_root

REPO_ROOT = find_repo_root()
pytestmark = pytest.mark.skipif(
    REPO_ROOT is None,
    reason="repo root not visible from this environment (e.g. the api Docker image only "
    "copies services/api to /app) - run against a full dev checkout to exercise these",
)
RELEASE_CANDIDATE_AUDIT_SCRIPT = (
    REPO_ROOT / "scripts" / "release_candidate_audit.sh" if REPO_ROOT else None
)
FINAL_AUDIT_SCRIPT = REPO_ROOT / "scripts" / "final_audit.sh" if REPO_ROOT else None


def test_release_candidate_audit_script_exists():
    assert RELEASE_CANDIDATE_AUDIT_SCRIPT.is_file()


def test_release_candidate_audit_script_is_executable():
    assert os.access(RELEASE_CANDIDATE_AUDIT_SCRIPT, os.X_OK)


def test_final_audit_references_release_candidate_audit_script():
    contents = FINAL_AUDIT_SCRIPT.read_text()
    assert "release_candidate_audit.sh" in contents


def test_release_candidate_audit_script_prints_pass_message():
    contents = RELEASE_CANDIDATE_AUDIT_SCRIPT.read_text()
    assert "Release candidate audit passed" in contents


def test_release_candidate_report_exists():
    assert (REPO_ROOT / "docs" / "release_candidate_report.md").is_file()


def test_release_blockers_doc_exists():
    assert (REPO_ROOT / "docs" / "release_blockers.md").is_file()


def test_version_file_is_v1():
    version = (REPO_ROOT / "VERSION").read_text().strip()
    assert version == "1.0.0"
