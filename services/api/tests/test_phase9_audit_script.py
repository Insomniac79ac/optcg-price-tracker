"""Sanity checks that scripts/phase9_audit.sh (the Phase 9 catalog-operations
completion audit) exists, is executable, and that scripts/final_audit.sh
knows about it - mirrors how Phase 7/8's audit scripts are wired into
final_audit.sh, just verified from the test suite instead of only read by a
human. Does not actually run the script (it needs a live docker compose
stack) - see docs/operations.md's 'Catalog operations workflow'."""

import os

import pytest

from tests._repo_root import find_repo_root

REPO_ROOT = find_repo_root()
pytestmark = pytest.mark.skipif(
    REPO_ROOT is None,
    reason="repo root not visible from this environment (e.g. the api Docker image only "
    "copies services/api to /app) - run against a full dev checkout to exercise these",
)
PHASE9_AUDIT_SCRIPT = REPO_ROOT / "scripts" / "phase9_audit.sh" if REPO_ROOT else None
FINAL_AUDIT_SCRIPT = REPO_ROOT / "scripts" / "final_audit.sh" if REPO_ROOT else None


def test_phase9_audit_script_exists():
    assert PHASE9_AUDIT_SCRIPT.is_file()


def test_phase9_audit_script_is_executable():
    assert os.access(PHASE9_AUDIT_SCRIPT, os.X_OK)


def test_final_audit_references_phase9_audit_script():
    contents = FINAL_AUDIT_SCRIPT.read_text()
    assert "phase9_audit.sh" in contents


def test_phase9_audit_script_prints_pass_message():
    contents = PHASE9_AUDIT_SCRIPT.read_text()
    assert "Phase 9 audit passed" in contents
