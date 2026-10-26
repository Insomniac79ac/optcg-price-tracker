"""yuyu-source-probe (scripts/ops/yuyu_probe.py): preconditions, plan digest, apply gate, SQL on the schema."""
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ops import common, run, yuyu_probe as yp  # noqa: E402

AT = datetime(2026, 10, 25, 16, 27, tzinfo=timezone.utc)


def facts(**over):
    base = {
        "budget": {"source_id": 2, "enabled": True, "pause_reason": "source_denial", "paused_until": None,
                   "reserved_requests": 0, "used_requests": 10, "request_limit": 100000},
        "denial": {"attempt_id": 900, "finished_at": AT, "work_kind": "refresh", "work_id": 5,
                   "failure": "source_denial;no_extraction_attempted:classification=challenge_or_captcha"},
        "mapping": {"mapping_id": 77, "card_print_id": 66, "product_identity": "yuyutei:op01:10001",
                    "source_url": "https://yuyu-tei.jp/sell/opc/card/op01/10001", "last_success": AT},
        "existing_probe": None,
    }
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


class Plan(unittest.TestCase):
    def test_a_paused_source_with_a_refresh_denial_plans_one_probe(self):
        p, problems = yp.plan(facts())
        self.assertEqual(problems, [])
        self.assertEqual((p["denial_attempt_id"], p["mapping_id"]), (900, 77))
        self.assertEqual(len(yp.plan_sha(p)), 64)

    def test_every_precondition_refuses(self):
        cases = {
            "not paused": facts(budget={"pause_reason": None}),
            "timed pause": facts(budget={"paused_until": AT}),
            "disabled": facts(budget={"enabled": False}),
            "probe denial": facts(denial={"work_kind": "validation"}),
            "no denial": facts(denial=None),
            "replay": facts(existing_probe={"id": 1, "state": "blocked"}),
            "no mapping": facts(mapping=None),
            "reserved": facts(budget={"reserved_requests": 3}),
        }
        for name, f in cases.items():
            with self.subTest(name):
                p, problems = yp.plan(f)
                self.assertIsNone(p)
                self.assertTrue(problems)

    def test_sha_moves_with_any_plan_field(self):
        p, _ = yp.plan(facts())
        q, _ = yp.plan(facts(mapping={"mapping_id": 78}))
        self.assertNotEqual(yp.plan_sha(p), yp.plan_sha(q))

    def test_registered_as_collector_affecting_write(self):
        self.assertEqual(run.RUNBOOKS["yuyu-source-probe"][:2], ("write", True))


class RunFlow(unittest.TestCase):
    def test_dry_run_writes_nothing_and_reports_the_sha(self):
        written = []
        with tempfile.TemporaryDirectory() as tmp:
            out = yp.run(tmp, read=lambda: facts(), write=written.append)
            self.assertTrue((Path(tmp) / "yuyu-source-probe.json").is_file())
        self.assertTrue(out["ok"])
        self.assertEqual(written, [])
        self.assertEqual(out["probe_mapping"]["mapping_id"], 77)

    def test_apply_needs_the_dry_run_sha_and_writes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            sha = yp.run(tmp, read=lambda: facts())["plan_sha256"]
            written = []
            out = yp.run(tmp, apply=True, expected_sha256=sha, read=lambda: facts(),
                         write=lambda p: written.append(p) or 4242)
            self.assertEqual((out["probe_work_id"], len(written)), (4242, 1))
            with self.assertRaises(common.Refused):
                yp.run(tmp, apply=True, expected_sha256="0" * 64, read=lambda: facts(), write=written.append)
            with self.assertRaises(common.Refused):
                yp.run(tmp, apply=True, expected_sha256=sha, read=lambda: facts(budget={"pause_reason": None}),
                       write=written.append)
        self.assertEqual(len(written), 1)

    def test_dry_run_with_a_problem_reports_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = yp.run(tmp, read=lambda: facts(existing_probe={"id": 3}))
        self.assertFalse(out["ok"])
        self.assertIsNone(out["plan_sha256"])


@unittest.skipUnless(os.environ.get("OPS_TEST_POSTGRES_URL"), "needs OPS_TEST_POSTGRES_URL")
class SqlOnSchema(unittest.TestCase):
    def test_fact_queries_run_read_only_on_the_schema(self):
        import psycopg
        from psycopg.rows import dict_row
        import sqlalchemy as sa
        import app.models  # noqa: F401
        from app.db import Base
        from ops import db as ops_db

        url = os.environ["OPS_TEST_POSTGRES_URL"]
        engine = sa.create_engine(url)
        Base.metadata.create_all(engine)
        engine.dispose()
        with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://"), options=ops_db.options(),
                             row_factory=dict_row) as conn:
            with self.assertRaises(common.Refused):  # empty schema: no Yuyu-Tei budget
                yp.read_facts(conn)
            conn.rollback()
            for sql, params in ((yp.DENIAL_SQL, {"source_id": 1}), (yp.MAPPING_SQL, {"source_id": 1}),
                                (yp.PROBE_SQL, {"source_id": 1, "scope": "x"})):
                self.assertEqual(conn.execute(sql, params).fetchall(), [])


if __name__ == "__main__":
    unittest.main()
