"""yuyu-source-probe (scripts/ops/yuyu_probe.py): dry run, plan digest and apply gate.

The plan itself (preconditions, pause chain, cap, cool-down, mapping choice) is
app.services.source_recovery.preview_yuyu_probe, tested on PostgreSQL in
services/api/tests/test_yuyu_probe_postgres.py; here the preview is a stand-in."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ops import common, run, yuyu_probe as yp  # noqa: E402

PLAN = {"source_id": 2, "root_denial_attempt_id": 900, "denial_attempt_id": 900, "probe_number": 1,
        "mapping_id": 77, "card_print_id": 66, "product_identity": "op01:10001", "request_bound": 60}
FACTS = {"budget": {"pause_reason": "source_denial"},
         "denial": {"attempt_id": 900, "at": "2026-10-25T16:27:00+00:00", "work_kind": "refresh"},
         "root_denial_attempt_id": 900, "probes": [],
         "mapping": {"mapping_id": 77, "card_print_id": 66, "source_url": "https://yuyu-tei.jp/x",
                     "last_success": "2026-10-25T10:00:00+00:00"}}


def preview(plan=PLAN, problems=()):
    return lambda: (dict(plan) if plan else None, list(problems), FACTS)


class Plan(unittest.TestCase):
    def test_sha_covers_every_plan_key_from_the_api(self):
        from app.services.source_recovery import YUYU_PROBE_PLAN_KEYS

        self.assertEqual(set(PLAN), set(YUYU_PROBE_PLAN_KEYS))
        base = yp.plan_sha(PLAN)
        self.assertEqual(len(base), 64)
        for key in YUYU_PROBE_PLAN_KEYS:
            changed = {**PLAN, key: PLAN[key] + 1 if isinstance(PLAN[key], int) else PLAN[key] + "x"}
            self.assertNotEqual(yp.plan_sha(changed), base, key)

    def test_registered_as_collector_affecting_write(self):
        self.assertEqual(run.RUNBOOKS["yuyu-source-probe"][:2], ("write", True))


class RunFlow(unittest.TestCase):
    def test_dry_run_writes_nothing_and_reports_the_sha(self):
        written = []
        with tempfile.TemporaryDirectory() as tmp:
            out = yp.run(tmp, preview=preview(), write=written.append)
            self.assertTrue((Path(tmp) / "yuyu-source-probe.json").is_file())
        self.assertTrue(out["ok"])
        self.assertEqual(written, [])
        self.assertEqual((out["probe_mapping"]["mapping_id"], out["pause_chain_root"], out["probe_number"]),
                         (77, 900, 1))
        self.assertEqual(out["plan_sha256"], yp.plan_sha(PLAN))

    def test_apply_needs_the_dry_run_sha_and_writes_the_plan_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            sha = yp.run(tmp, preview=preview())["plan_sha256"]
            written = []
            out = yp.run(tmp, apply=True, expected_sha256=sha, preview=preview(),
                         write=lambda p: written.append(p) or 4242)
            self.assertEqual((out["probe_work_id"], written), (4242, [PLAN]))
            with self.assertRaises(common.Refused):
                yp.run(tmp, apply=True, expected_sha256="0" * 64, preview=preview(), write=written.append)
            with self.assertRaises(common.Refused):  # the facts moved since the dry run
                yp.run(tmp, apply=True, expected_sha256=sha, preview=preview({**PLAN, "mapping_id": 78}),
                       write=written.append)
            with self.assertRaises(common.Refused):
                yp.run(tmp, apply=True, expected_sha256=sha, preview=preview(None, ["not paused"]),
                       write=written.append)
        self.assertEqual(len(written), 1)

    def test_dry_run_with_a_problem_reports_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = yp.run(tmp, preview=preview(None, ["an earlier probe of this pause is still open"]))
        self.assertFalse(out["ok"])
        self.assertIsNone(out["plan_sha256"])
        self.assertEqual(out["problems"], ["an earlier probe of this pause is still open"])


if __name__ == "__main__":
    unittest.main()
