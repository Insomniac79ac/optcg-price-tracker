"""market-value-freeze-legacy runbook gate (owner plan A, 2026-10-28). The plan itself is tested
against a real catalogue in services/api/tests/test_market_value_publisher.py."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ops import common, mv_freeze_legacy as runbook  # noqa: E402
from ops import run  # noqa: E402

PLAN = {"memberships": [{"revision": "current-corrected-card-print-release-v1:" + "a" * 64,
                         "prints": 3579, "coded_releases": 60, "content_sha256": "b" * 64}]}
FACTS = {"stored_revisions": 1, "unfrozen": 1, "rebuilds": [{"digest_matches": True}]}


class FreezeLegacy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)

    def go(self, preview, **kwargs):
        return runbook.run(self.out, preview=lambda: preview, **kwargs)

    def test_registered_as_a_non_collector_write(self):
        self.assertEqual(run.RUNBOOKS["market-value-freeze-legacy"][:2], ("write", False))

    def test_dry_run_reports_the_plan_and_its_sha(self):
        summary = self.go((PLAN, [], FACTS))
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["plan_sha256"], runbook.plan_sha(PLAN))
        self.assertEqual(summary["database_writes_planned"], 3579 + 60 + 1)
        self.assertTrue((self.out / "market-value-freeze-legacy.json").exists())

    def test_problems_block_apply(self):
        self.assertFalse(self.go((None, ["cannot be rebuilt exactly"], FACTS))["ok"])
        with self.assertRaisesRegex(common.Refused, "nothing to freeze"):
            self.go((None, ["cannot be rebuilt exactly"], FACTS), apply=True, expected_sha256="0" * 64)

    def test_apply_needs_the_dry_run_sha(self):
        sha = runbook.plan_sha(PLAN)
        for bad in ("", "0" * 64, sha.upper(), sha[:-1]):
            with self.subTest(bad=bad), self.assertRaisesRegex(common.Refused, "expected_sha256"):
                self.go((PLAN, [], FACTS), apply=True, expected_sha256=bad, write=lambda p: self.fail("wrote"))
        written = []
        summary = self.go((PLAN, [], FACTS), apply=True, expected_sha256=sha,
                          write=lambda p: written.append(p) or [e["revision"] for e in p["memberships"]])
        self.assertEqual(written, [PLAN])
        self.assertEqual(summary["frozen"], [PLAN["memberships"][0]["revision"]])

    def test_count_is_refused(self):
        class Args:
            count, apply, expected_sha256 = 1, False, ""
        with self.assertRaisesRegex(common.Refused, "takes no count"):
            run._mv_freeze_legacy(Args, self.out)


if __name__ == "__main__":
    unittest.main()
