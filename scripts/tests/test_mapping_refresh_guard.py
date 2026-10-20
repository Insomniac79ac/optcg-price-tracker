"""Every code path that writes an approved source mapping also plans its refresh work.

A mapping approved without a `refresh` row in freshness_work is never collected (F1 batch 1,
2026-10-19: 97 approved mappings, no refresh work). The shared call is
app.services.mapping_refresh.ensure_refresh_work; this test fails when a module under
services/api/app writes `review_status = "approved"` on a mapping (an assignment, or a
SourceCardMapping(...) with review_status="approved") without calling it. No database.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "services/api/app"
APPROVED_NAMES = {"APPROVED", "APPROVED_REVIEW_STATUS"}
MAPPING_NAMES = {"mapping", "m", "existing_mapping", "row"}
# Writers that are not an approval a collector acts on, each with its reason.
EXEMPT = {
    # The official display-image source; no collector refreshes it (not yuyutei or snkrdunk).
    "services/api/app/services/official_display_evidence.py",
    # Development seed data.
    "services/api/app/seed.py",
}


def _is_approved(node):
    if isinstance(node, ast.Constant):
        return node.value == "approved"
    if isinstance(node, ast.Name):
        return node.id in APPROVED_NAMES
    if isinstance(node, ast.IfExp):
        return _is_approved(node.body) or _is_approved(node.orelse)
    return False


def approval_writes(tree):
    """Line numbers where the module writes an approved mapping."""
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Attribute) and target.attr == "review_status"
                        and isinstance(target.value, ast.Name) and target.value.id in MAPPING_NAMES
                        and _is_approved(node.value)):
                    lines.append(node.lineno)
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name == "SourceCardMapping" and any(
                    k.arg == "review_status" and _is_approved(k.value) for k in node.keywords):
                lines.append(node.lineno)
    return lines


def calls_ensure(tree):
    return any(isinstance(node, ast.Call)
               and (getattr(node.func, "id", None) or getattr(node.func, "attr", None)) == "ensure_refresh_work"
               for node in ast.walk(tree))


class MappingRefreshGuard(unittest.TestCase):
    def test_every_approval_writer_plans_refresh_work(self):
        offenders, writers = [], []
        for path in sorted(APP.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            lines = approval_writes(tree)
            if not lines or rel in EXEMPT:
                continue
            writers.append(rel)
            if not calls_ensure(tree):
                offenders.append(f"{rel}:{lines[0]}")
        self.assertEqual(offenders, [], "approves a mapping without ensure_refresh_work")
        # The scan must keep seeing the known writers, or it has gone blind.
        for known in ("services/api/app/services/yuyutei_candidate_approval.py",
                      "services/api/app/services/snkrdunk_candidate_approval.py",
                      "services/api/app/api/snkrdunk_candidates.py",
                      "services/api/app/api/source_mappings.py",
                      "services/api/app/api/admin_source_mapping_quality.py"):
            self.assertIn(known, writers)

    def test_scan_flags_a_writer_without_the_call(self):
        tree = ast.parse("def f(db, mapping):\n    mapping.review_status = 'approved'\n")
        self.assertEqual(approval_writes(tree), [2])
        self.assertFalse(calls_ensure(tree))

    def test_exempt_files_exist(self):
        for rel in EXEMPT:
            self.assertTrue((ROOT / rel).is_file(), rel)


if __name__ == "__main__":
    unittest.main()
