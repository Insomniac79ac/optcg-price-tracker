"""Sanity checks that scripts/phase9_audit.sh (the Phase 9 catalog-operations
completion audit) exists, is executable, and that scripts/final_audit.sh
knows about it - mirrors how Phase 7/8's audit scripts are wired into
final_audit.sh, just verified from the test suite instead of only read by a
human. Does not actually run the script (it needs a live docker compose
stack) - see docs/operations.md's 'Catalog operations workflow'."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PHASE9_AUDIT_SCRIPT = REPO_ROOT / "scripts" / "phase9_audit.sh"
FINAL_AUDIT_SCRIPT = REPO_ROOT / "scripts" / "final_audit.sh"


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
