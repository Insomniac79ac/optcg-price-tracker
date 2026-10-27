"""snkr-parser-requeue (scripts/ops/snkr_requeue.py): mode from count, plan digest, apply gate.

The plan itself is app.services.snkr_parser_requeue.preview, tested on PostgreSQL in
services/api/tests/test_snkr_parser_requeue_postgres.py; here the preview is a stand-in."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ops import common, run, snkr_requeue as sr  # noqa: E402

PLAN = {"source_id": 1, "mode": "canary", "work_ids": [4711]}
FACTS = {"candidates": 284, "ineligible": [], "proven_captures": [], "open_requeues": [], "refused_on_new_code": []}


def preview(plan=PLAN, problems=()):
    seen = []

    def fake(mode):
        seen.append(mode)
        return (dict(plan) if plan else None, list(problems), FACTS)
    fake.seen = seen
    return fake


class Plan(unittest.TestCase):
    def test_count_one_is_the_canary_and_empty_is_the_rest(self):
        self.assertEqual((sr.mode_for(1), sr.mode_for(None)), ("canary", "rest"))
        with self.assertRaises(common.Refused):
            sr.mode_for(5)

    def test_sha_covers_every_plan_key_from_the_api(self):
        from app.services.snkr_parser_requeue import PLAN_KEYS

        self.assertEqual(set(PLAN), set(PLAN_KEYS))
        base = sr.plan_sha(PLAN)
        for changed in ({**PLAN, "source_id": 2}, {**PLAN, "mode": "rest"}, {**PLAN, "work_ids": [4712]}):
            self.assertNotEqual(sr.plan_sha(changed), base)

    def test_registered_as_collector_affecting_write(self):
        self.assertEqual(run.RUNBOOKS["snkr-parser-requeue"][:2], ("write", True))


class RunFlow(unittest.TestCase):
    def test_dry_run_writes_nothing_and_reports_the_plan(self):
        written, fake = [], preview()
        with tempfile.TemporaryDirectory() as tmp:
            out = sr.run(tmp, count=1, preview=fake, write=written.append)
            self.assertTrue((Path(tmp) / "snkr-parser-requeue.json").is_file())
        self.assertEqual((out["ok"], out["reopen"], out["candidates"], fake.seen), (True, 1, 284, ["canary"]))
        self.assertEqual(written, [])

    def test_apply_needs_the_dry_run_sha_and_writes_the_plan_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            sha = sr.run(tmp, count=1, preview=preview())["plan_sha256"]
            written = []
            out = sr.run(tmp, apply=True, count=1, expected_sha256=sha, preview=preview(),
                         write=lambda p: written.append(p) or p["work_ids"])
            self.assertEqual((out["written"], written), (1, [PLAN]))
            with self.assertRaises(common.Refused):
                sr.run(tmp, apply=True, count=1, expected_sha256="0" * 64, preview=preview(), write=written.append)
            with self.assertRaises(common.Refused):
                sr.run(tmp, apply=True, count=1, expected_sha256=sha, preview=preview({**PLAN, "work_ids": [9]}),
                       write=written.append)
            with self.assertRaises(common.Refused):
                sr.run(tmp, apply=True, count=None, expected_sha256=sha, preview=preview(None, ["no proof"]),
                       write=written.append)
        self.assertEqual(len(written), 1)

    def test_dry_run_with_a_problem_reports_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = sr.run(tmp, preview=preview(None, ["no refused item has captured a price on the new code yet"]))
        self.assertFalse(out["ok"])
        self.assertIsNone(out["plan_sha256"])


if __name__ == "__main__":
    unittest.main()
