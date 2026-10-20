import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from staging_delivery_scope import allowlisted, decide, main, parse_name_status
from staging_mission import FLEET, LEGACY_MANIFEST

DOC = "docs/agent/handoff/2026-10-08/x/HANDOFF.md"
MISSION = "docs/agent/missions/claude-docs.json"
QUIET = {"mission": "docs"}
ROLLOUT = {"deployment_verification": {"collector_services": [{"name": "snkrdunk-collector"}]}}
DDL = {"deployment_verification": {"raw_dependency_migration": {"revision": "f9e5b4a8c012"}}}


class ScopeDecisionTests(unittest.TestCase):
    def test_docs_only_skips(self):
        r = decide([("A", [DOC]), ("M", ["docs/operations.md"]), ("A", [MISSION])], QUIET)
        self.assertEqual(r["decision"], "skip")
        self.assertEqual(decide([("A", [DOC]), ("A", [MISSION])], {})["decision"], "skip")

    def test_docs_without_mission_skips(self):
        self.assertEqual(decide([("A", [DOC])], None)["decision"], "skip")

    def test_docs_and_code_runs_full(self):
        r = decide([("A", [DOC]), ("M", ["services/api/app/main.py"])], QUIET)
        self.assertEqual(r["decision"], "full")
        self.assertEqual(r["outside_allowlist"], ["services/api/app/main.py"])

    def test_mission_requesting_rollout_or_migration_runs_full(self):
        for mission in (ROLLOUT, DDL):
            self.assertEqual(decide([("A", [DOC]), ("A", [MISSION])], mission)["decision"], "full")

    def test_mission_only_or_unreadable_runs_full(self):
        self.assertEqual(decide([("A", [MISSION])], QUIET)["decision"], "full")
        self.assertEqual(decide([("A", [DOC]), ("A", [MISSION])], None)["decision"], "full")
        self.assertEqual(decide([("A", [DOC]), ("A", [MISSION])],
                                {"deployment_verification": []})["decision"], "full")

    def test_changed_removed_or_second_mission_runs_full(self):
        other = "docs/agent/missions/claude-other.json"
        for rows in ([("A", [DOC]), ("M", [MISSION])], [("A", [DOC]), ("D", [MISSION])],
                     [("A", [DOC]), ("A", [MISSION]), ("A", [other])],
                     [("A", [DOC]), ("R100", [other, MISSION])]):
            with self.subTest(rows=rows):
                self.assertEqual(decide(rows, QUIET)["decision"], "full")

    def test_fleet_or_legacy_manifest_change_runs_full(self):
        for path in (FLEET, LEGACY_MANIFEST):
            with self.subTest(path=path):
                r = decide([("A", [DOC]), ("A", [MISSION]), ("M", [path])], QUIET)
                self.assertEqual(r["decision"], "full")
                self.assertEqual(r["outside_allowlist"], [path])

    def test_empty_change_set_runs_full(self):
        self.assertEqual(decide([], QUIET)["decision"], "full")

    def test_rename_into_or_out_of_docs_runs_full(self):
        self.assertEqual(decide([("R100", ["scripts/x.py", DOC])], QUIET)["decision"], "full")
        self.assertEqual(decide([("R090", [DOC, "scripts/x.py"])], QUIET)["decision"], "full")
        self.assertEqual(decide([("R100", [DOC, "docs/agent/handoff/y.md"])], QUIET)["decision"], "skip")

    def test_unknown_status_runs_full(self):
        self.assertEqual(decide([("T", [DOC])], QUIET)["decision"], "full")

    def test_operational_docs_are_never_allowlisted(self):
        for path in (LEGACY_MANIFEST, FLEET, MISSION, "docs/agent/CURRENT_STATE.yaml", "docs/agent/evidence/staging-state-read.sql",
                     "docs/agent/evidence/notes.md", "docs/agent/STAGING_MISSION.md.json", "docs/x.py",
                     "apps/web/README.md", "README.md"):
            self.assertFalse(allowlisted(path), path)
        for path in (DOC, "docs/agent/handoff/a/data.json", "docs/agent/PROJECT_HANDOVER.md"):
            self.assertTrue(allowlisted(path), path)

    def test_malformed_name_status_is_refused(self):
        with self.assertRaises(ValueError):
            parse_name_status("R100\0only-one-path\0")
        self.assertEqual(parse_name_status(f"M\0{DOC}\0R100\0a\0b\0"), [("M", [DOC]), ("R100", ["a", "b"])])


class ScopeGitTests(unittest.TestCase):
    def repo(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        run = lambda *a: subprocess.run(["git", *a], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
        run("init", "-q")
        run("config", "user.email", "t@example.invalid")
        run("config", "user.name", "t")
        # No detached auto-maintenance racing TemporaryDirectory cleanup.
        run("config", "maintenance.auto", "false")
        run("config", "gc.auto", "0")
        (root / "docs/agent").mkdir(parents=True)
        (root / FLEET).write_text(json.dumps({"schema_version": 1}))
        (root / "app.py").write_text("x = 1\n")
        run("add", ".")
        run("commit", "-qm", "base")
        return root, run

    def scope(self, root, merge):
        out = root / "out.json"
        cwd = Path.cwd()
        try:
            os.chdir(root)
            main(["--merge", merge, "--output", str(out)])
        finally:
            os.chdir(cwd)
        return json.loads(out.read_text())

    def test_git_docs_only_merge_skips_and_records_files(self):
        root, run = self.repo()
        (root / "docs/agent/handoff").mkdir()
        (root / DOC.replace("2026-10-08/x/", "")).write_text("notes\n")
        run("add", ".")
        run("commit", "-qm", "docs")
        r = self.scope(root, run("rev-parse", "HEAD"))
        self.assertEqual(r["decision"], "skip")
        self.assertEqual(r["files"], ["docs/agent/handoff/HANDOFF.md"])

    def test_git_docs_and_quiet_mission_skip_but_requests_run_full(self):
        root, run = self.repo()
        (root / "docs/agent/missions").mkdir()
        (root / "docs/agent/notes.md").write_text("notes\n")
        (root / MISSION).write_text(json.dumps(QUIET))
        run("add", ".")
        run("commit", "-qm", "docs with mission")
        self.assertEqual(self.scope(root, run("rev-parse", "HEAD"))["decision"], "skip")
        (root / "out.json").unlink()
        (root / "docs/agent/more.md").write_text("more\n")
        (root / "docs/agent/missions/claude-rollout.json").write_text(json.dumps(ROLLOUT))
        run("add", ".")
        run("commit", "-qm", "docs with rollout")
        r = self.scope(root, run("rev-parse", "HEAD"))
        self.assertEqual(r["decision"], "full")
        self.assertEqual(r["requested"], ["collector_services"])

    def test_git_code_change_runs_full(self):
        root, run = self.repo()
        (root / "app.py").write_text("x = 2\n")
        run("commit", "-qam", "code")
        self.assertEqual(self.scope(root, run("rev-parse", "HEAD"))["decision"], "full")

    def test_git_unknown_merge_fails_closed(self):
        root, run = self.repo()
        r = self.scope(root, "0" * 40)
        self.assertEqual(r["decision"], "full")
        self.assertIn("undetermined", r["reason"])


if __name__ == "__main__":
    unittest.main()
