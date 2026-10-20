import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import staging_verify_head as head
import yaml


class HeadTests(unittest.TestCase):
    merged, newer = "a" * 40, "b" * 40

    def run_main(self, expected, current):
        calls = []
        def read():
            calls.append(1)
            return current
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.write_text("")
            stdout = io.StringIO()
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(out)}), contextlib.redirect_stdout(stdout):
                code = head.main(["--expected", expected], head=read)
            return code, out.read_text(), stdout.getvalue(), calls

    def test_current_head_verifies(self):
        code, out, stdout, _ = self.run_main(self.merged, self.merged)
        self.assertEqual((code, out, stdout), (0, "current=true\n", ""))

    def test_stale_dispatch_exits_as_obsolete(self):
        code, out, stdout, _ = self.run_main(self.merged, self.newer)
        self.assertEqual((code, out), (0, "current=false\n"))
        self.assertIn("Obsolete", stdout)

    def test_malformed_expected_fails_before_reading_the_head(self):
        for bad in ("", "a" * 39, "A" * 40, "a" * 40 + "\n", "staging", "8693ff8c"):
            with self.assertRaises(SystemExit) as raised:
                self.run_main(bad, self.merged)
            self.assertNotEqual(raised.exception.code, 0)
        calls = []
        with self.assertRaises(SystemExit):
            head.main(["--expected", "abc"], head=lambda: calls.append(1) or self.merged)
        self.assertEqual(calls, [])

    def test_unreadable_head_fails(self):
        with self.assertRaises(SystemExit):
            self.run_main(self.merged, "")


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        text = (SCRIPTS.parent / ".github/workflows/staging-verify.yml").read_text()
        self.workflow = yaml.load(text, Loader=yaml.BaseLoader)
        self.job = self.workflow["jobs"]["verify"]

    def test_dispatch_takes_a_required_expected_sha(self):
        on = self.workflow["on"]
        self.assertEqual(on["push"]["branches"], ["staging"])
        self.assertEqual(on["workflow_dispatch"]["inputs"]["expected_sha"]["required"], "true")

    def test_dispatch_runs_only_from_staging(self):
        self.assertIn("github.event_name == 'push' || github.ref == 'refs/heads/staging'", self.job["if"])

    def test_expected_is_the_input_else_the_pushed_sha(self):
        steps = {step.get("name", step.get("uses", "")): step for step in self.job["steps"]}
        expected = "${{ inputs.expected_sha || github.sha }}"
        self.assertEqual(steps["actions/checkout@v4"]["with"]["ref"], expected)
        verify = steps["Verify current staging head"]
        self.assertEqual(verify["env"]["EXPECTED"], expected)
        run = verify["run"]
        gate = run.index('python scripts/staging_verify_head.py --expected "$EXPECTED"')
        self.assertLess(gate, run.index("staging_mission.py compose"))
        self.assertIn("if ! grep -qx 'current=true' \"$GITHUB_OUTPUT\"; then exit 0; fi", run)
        self.assertNotIn("${{ inputs", run)

    def test_timeout_covers_both_waits(self):
        self.assertGreaterEqual(int(self.job["timeout-minutes"]), 40)


if __name__ == "__main__":
    unittest.main()
