"""Ops runbooks (scripts/ops): arithmetic against committed evidence, guards, read-only SQL.

Offline except DiagnosticsOnPostgres, which needs OPS_TEST_POSTGRES_URL (CI sets it and
REQUIRE_POSTGRES=1, so a missing database fails instead of skipping).
"""
import contextlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ops import common, diagnostic, enqueue_remaining, fleet, official_images, replan, run, staging_state, storage_rates  # noqa: E402
from ops import db as ops_db, lossless  # noqa: E402

S13 = ROOT / "docs/agent/handoff/2026-10-15/capacity75-session13/evidence"


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class StorageRates(unittest.TestCase):
    def test_reproduces_session13_rates_from_committed_series(self):
        result = storage_rates.compute(json.loads((S13 / "volume-series-5min.json").read_text()))
        v = result["variants"]
        self.assertEqual(result["room_to_reserve_mb_s9"], 2970.3)
        self.assertEqual(result["steps"]["new50"]["mb_s9"], 66.5)
        self.assertEqual(v["as_observed"]["planning_mb_day_s9"], 37.68)          # storage-rates-current-code.json
        self.assertEqual(v["as_observed"]["stress_worst_rolling_24h"]["mb_day_s9"], 109.26)
        self.assertEqual(v["ex_steps"]["planning_mb_day_s9"], 23.10)              # storage-rates-ex-new50.json
        self.assertEqual(v["ex_steps"]["stress_worst_rolling_24h"]["mb_day_s9"], 42.79)
        self.assertEqual(v["ex_steps_ex_transients"]["stress_worst_rolling_24h"]["mb_day_s9"], 26.41)
        self.assertEqual(result["transients_excluded"]["2026-10-14-04z"]["samples"], 13)
        self.assertEqual(result["last_24h_mb_s9"], 26.32)

    def test_no_transient_named_keeps_as_observed_stress(self):
        result = storage_rates.compute(json.loads((S13 / "volume-series-5min.json").read_text()), transients=[])
        v = result["variants"]
        self.assertEqual(v["ex_steps_ex_transients"]["stress_worst_rolling_24h"], v["ex_steps"]["stress_worst_rolling_24h"])

    def test_unknown_transient_refused(self):
        with self.assertRaises(common.Refused):
            storage_rates.compute(json.loads((S13 / "volume-series-5min.json").read_text()), transients=["made-up"])

    def test_fit_matches_session13_remaining50(self):
        expected = json.loads((S13 / "remaining50-fit.json").read_text())
        doc = {"entries": [{"considered_print_ids": [1, 2]}] * 35 + [{"considered_print_ids": [1, 2, 3]}] * 15}
        self.assertEqual(sum(len(e["considered_print_ids"]) for e in doc["entries"]), 115)
        one_off = enqueue_remaining.one_off_mb(doc, expected)
        self.assertEqual(one_off, 70.6)
        fit = storage_rates.fit({"planning": 23.10, "stress": 42.79}, one_off, 2970.3, 90, 0.45)
        self.assertEqual(fit["planning"]["margin_mb"], expected["rates"]["planning"]["margin_mb"])
        self.assertTrue(fit["planning"]["fits"])
        self.assertFalse(fit["stress"]["fits"])


class QuietWindowsAndPreflight(unittest.TestCase):
    def args(self, runbook, workflow="ops-readonly", apply=False):
        return mock.Mock(runbook=runbook, workflow=workflow, apply=apply)

    def test_windows(self):
        refuse = common.quiet_window_refusal
        self.assertIsNotNone(refuse(utc(2026, 10, 16, 2, 0), collector_affecting=True, write=False))
        self.assertIsNotNone(refuse(utc(2026, 10, 16, 5, 59), collector_affecting=True, write=False))
        self.assertIsNone(refuse(utc(2026, 10, 16, 6, 0), collector_affecting=True, write=False))
        self.assertIsNotNone(refuse(utc(2026, 10, 16, 19, 30), collector_affecting=False, write=True))
        self.assertIsNone(refuse(utc(2026, 10, 16, 20, 30), collector_affecting=False, write=True))
        self.assertIsNone(refuse(utc(2026, 10, 16, 3, 0), collector_affecting=False, write=False))

    def test_every_read_runbook_runs_any_time(self):
        for name, (kind, collector, _) in run.RUNBOOKS.items():
            if kind == "read":
                self.assertFalse(collector)
                for hour in (3, 19):
                    run.preflight(self.args(name), now=utc(2026, 10, 16, hour, 45), read=None)

    def test_write_runbook_only_in_ops_write(self):
        with self.assertRaisesRegex(common.Refused, "ops-write"):
            run.preflight(self.args("enqueue-remaining-50"), now=utc(2026, 10, 16, 12), read=None)

    def test_enqueue_apply_respects_both_windows(self):
        idle = lambda path: {"workflow_runs": []}  # noqa: E731
        for hour, minute in ((2, 30), (19, 45)):
            with self.assertRaises(common.Refused):
                run.preflight(self.args("enqueue-remaining-50", "ops-write", True), now=utc(2026, 10, 16, hour, minute), read=idle)
        run.preflight(self.args("enqueue-remaining-50", "ops-write", True), now=utc(2026, 10, 16, 12), read=idle)
        # A dry run writes nothing: no window applies.
        run.preflight(self.args("enqueue-remaining-50", "ops-write", False), now=utc(2026, 10, 16, 2, 30), read=idle)

    def test_write_refused_while_a_delivery_runs(self):
        def read(path):
            if "ci.yml/runs?status=in_progress" in path:
                return {"workflow_runs": [{"id": 7}]}
            if path.endswith("runs/7/jobs?per_page=100"):
                return {"jobs": [{"name": "backend-tests", "status": "in_progress"},
                                 {"name": "staging-automerge", "status": "in_progress"}]}
            return {"workflow_runs": []}
        self.assertEqual(run.deliveries_in_progress(read), ["ci.yml staging-automerge run 7"])
        with self.assertRaisesRegex(common.Refused, "delivery is in progress"):
            run.preflight(self.args("enqueue-remaining-50", "ops-write", False), now=utc(2026, 10, 16, 12), read=read)

    def test_ordinary_ci_is_not_a_delivery(self):
        def read(path):
            if "ci.yml/runs?status=in_progress" in path:
                return {"workflow_runs": [{"id": 8}]}
            if path.endswith("runs/8/jobs?per_page=100"):
                return {"jobs": [{"name": "frontend-build", "status": "in_progress"}]}
            return {"workflow_runs": []}
        self.assertEqual(run.deliveries_in_progress(read), [])

    def test_unknown_runbook_and_read_apply_refused(self):
        with self.assertRaises(common.Refused):
            run.preflight(self.args("drop-everything"), read=None)
        with self.assertRaises(common.Refused):
            run.preflight(self.args("staging-state", apply=True), read=None)


class WorkflowsMatchRegistry(unittest.TestCase):
    def options(self, workflow, key):
        import yaml
        data = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())
        return data[True]["workflow_dispatch"]["inputs"][key]["options"]  # YAML 1.1 reads `on` as True

    def test_choices(self):
        self.assertEqual(self.options("ops-readonly.yml", "runbook"),
                         [n for n, v in run.RUNBOOKS.items() if v[0] == "read"])
        self.assertEqual(self.options("ops-write.yml", "runbook"),
                         [n for n, v in run.RUNBOOKS.items() if v[0] == "write"])
        self.assertEqual(self.options("ops-readonly.yml", "diagnostic"), diagnostic.available())

    def test_delivery_workflows_have_runs_of_their_own(self):
        # A workflow_call-only workflow has no runs endpoint (404), which fails the preflight closed.
        import yaml
        for name in run.DELIVERY_WORKFLOWS:
            data = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
            self.assertTrue(set(data[True]) - {"workflow_call"}, name)

    def test_gates(self):
        ro = (ROOT / ".github/workflows/ops-readonly.yml").read_text()
        rw = (ROOT / ".github/workflows/ops-write.yml").read_text()
        self.assertIn("github.ref == 'refs/heads/staging'", ro)
        self.assertIn("workflow_dispatch", ro)
        self.assertNotIn("pull_request", ro + rw)
        approval, runbook = rw.split("\n  runbook:\n")
        self.assertIn("environment: staging-ops", approval)
        self.assertNotIn("secrets.", approval)
        self.assertIn("needs: owner-approval", runbook)
        # The push trigger only registers the workflow (dispatch needs it); no job runs on push.
        import yaml
        for name in ("ops-readonly.yml", "ops-write.yml"):
            data = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
            self.assertEqual(data[True]["push"], {"branches": ["staging"], "paths": [f".github/workflows/{name}"]})
            for job_name, job in data["jobs"].items():
                gate = job.get("if") or ("needs" in job and data["jobs"][job["needs"]]["if"])
                self.assertTrue(gate.startswith("github.event_name == 'workflow_dispatch' && "), job_name)
        # Free-text inputs reach the shell only through env, never inline expressions.
        for text in (ro, rw):
            for line in text.splitlines():
                if "${{ inputs." in line:
                    self.assertRegex(line.strip(), r"^(run-name|name|group|[A-Z0-9_]+):")


class SecretsStayOut(unittest.TestCase):
    def test_add_mask_and_scan(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), contextlib.redirect_stdout(out):
            common.register_secret("pg-password-123456")
        self.assertIn("::add-mask::pg-password-123456", out.getvalue())
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "ok.json").write_text("{}")
            common.assert_clean(tmp)
            (Path(tmp) / "leak.json").write_text('{"dsn": "pg-password-123456"}')
            with self.assertRaisesRegex(common.Refused, "leak.json"):
                common.assert_clean(tmp)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_env_tokens_are_scanned(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"RAILWAY_TOKEN": "railway-token-value"}):
            (Path(tmp) / "x.txt").write_text("railway-token-value")
            with self.assertRaises(common.Refused):
                common.assert_clean(tmp)

    def test_annotations_escape_and_chunk(self):
        lines = run.annotations({"a": "50%\nx", "b": "y" * 7000})
        self.assertTrue(all(line.startswith("::notice title=ops-summary ") for line in lines))
        self.assertEqual(len(lines), 3)
        joined = "".join(line.split("::", 2)[2] for line in lines)
        self.assertNotIn("\n", joined)
        self.assertIn('"a":"50%25', joined)


class ReadOnlyConnection(unittest.TestCase):
    def test_options_are_read_only(self):
        kwargs = ops_db.connect_kwargs({"domain": "h", "proxyPort": 1},
                                       {"PGUSER": "u", "PGPASSWORD": "p", "PGDATABASE": "d"})
        self.assertIn("-c default_transaction_read_only=on", kwargs["options"])
        self.assertIn("statement_timeout=60000", kwargs["options"])

    def test_verify_refuses_failed_fingerprint_or_writable_session(self):
        check = lambda ok: mock.Mock(ok=ok)  # noqa: E731
        conn = mock.Mock()
        conn.execute.return_value.fetchone.return_value = ("on",)
        guard = mock.Mock(evaluate=mock.Mock(return_value=[check(True)]),
                          expected_revisions_from_repo=mock.Mock(return_value=frozenset({"x"})))
        ops_db.verify(conn, guard)
        guard.evaluate.return_value = [SimpleNamespace(ok=False, name="tables")]
        with self.assertRaisesRegex(common.Refused, "fingerprint"):
            ops_db.verify(conn, guard)
        guard.evaluate.return_value = [check(True)]
        conn.execute.return_value.fetchone.return_value = ("off",)
        with self.assertRaisesRegex(common.Refused, "read-only"):
            ops_db.verify(conn, guard)


class Diagnostics(unittest.TestCase):
    def test_every_committed_file_parses(self):
        self.assertGreaterEqual(len(diagnostic.available()), 5)
        for name in diagnostic.available():
            self.assertTrue(diagnostic.load(name))

    def test_rejects_writes_and_tricks(self):
        for text in ("-- a\ninsert into x values (1);", "-- a\nselect 1; delete from x;",
                     "-- a\nwith d as (delete from x returning *) select * from d;",
                     "-- a\nselect set_config('x','y',false), 1 from t; ",
                     "-- a\nselect {{NOPE}};", "-- a\nupdate t set x=1;", "-- a\nselect pg_terminate_backend(1);"):
            with self.assertRaises(common.Refused, msg=text):
                diagnostic.parse(text, {"ELIGIBLE": "select 1"})
        self.assertEqual(diagnostic.parse("-- a\nselect 'delete' x from t;"), {"a": "select 'delete' x from t"})

    def test_unknown_name_refused(self):
        for name in ("../../etc/passwd", "nope", ""):
            with self.assertRaises(common.Refused):
                diagnostic.load(name)


@unittest.skipUnless(os.environ.get("OPS_TEST_POSTGRES_URL") or os.environ.get("REQUIRE_POSTGRES"),
                     "OPS_TEST_POSTGRES_URL not set")
class DiagnosticsOnPostgres(unittest.TestCase):
    """Every diagnostic runs on the real schema in a read-only session; a write is refused."""

    @classmethod
    def setUpClass(cls):
        url = os.environ.get("OPS_TEST_POSTGRES_URL")
        if not url:
            raise AssertionError("REQUIRE_POSTGRES=1 but OPS_TEST_POSTGRES_URL is not set")
        import sqlalchemy as sa
        import app.models  # noqa: F401
        import app.official_images.models  # noqa: F401
        from app.db import Base

        engine = sa.create_engine(url)
        Base.metadata.create_all(engine)
        engine.dispose()
        cls.dsn = url.replace("postgresql+psycopg://", "postgresql://")

    def test_all_diagnostics_read_only(self):
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(self.dsn, options=ops_db.options(), row_factory=dict_row) as conn:
            for name in diagnostic.available():
                result = diagnostic.execute(conn, diagnostic.load(name))
                self.assertTrue(result, name)
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                conn.execute("create table ops_write_probe (i int)")


class Lossless(unittest.TestCase):
    def rows(self):
        from opcg_source_identity.raw_payload import encode, sha256
        base = b"<html>" + b"base listing " * 400 + b"</html>"
        body = b"<html>" + b"base listing " * 399 + b"new price 1200</html>"
        stored = encode(body, base_id=10, base_body=base)
        base_row = {"id": 10, "raw_content": base.decode(), "content_hash": sha256(base),
                    "source_url": "u", "source_id": 1, "parser_version": "p"}
        row = {"id": 20, "stored": stored, "base_snapshot_id": 10, "expanded_at": None, "base_sha256": sha256(base),
               "original_sha256": sha256(body), "content_hash": sha256(body), "original_bytes": len(body),
               "encoded_bytes": len(stored.encode()), "http_status": 200, "source_url": "u", "source_id": 1,
               "parser_version": "p", "source": "yuyutei"}
        return row, base_row

    def fake_db(self, rows, base_row):
        class Result:
            def __init__(self, value):
                self.value = value

            def fetchone(self):
                return self.value

            def fetchall(self):
                return self.value

        class DB:
            def execute(self, sql, params=()):
                if "max(id)" in sql:
                    return Result({"m": max(r["id"] for r in rows)})
                if "from raw_snapshots where id" in sql:
                    return Result(base_row)
                return Result([r for r in rows if params[0] < r["id"] <= params[1]][:params[2]])

            def rollback(self):
                pass
        return DB()

    def test_lossless_and_corruption(self):
        row, base_row = self.rows()
        result = lossless.verify(self.fake_db([row], base_row), 19, progress=lambda _: None)
        self.assertTrue(result["all_lossless"])
        self.assertEqual((result["rows_checked"], result["next_floor_exclusive"]), (1, 20))
        bad = dict(row, original_sha256="0" * 64)
        result = lossless.verify(self.fake_db([bad], base_row), 19, progress=lambda _: None)
        self.assertFalse(result["all_lossless"])
        self.assertEqual(result["failures"][0]["id"], 20)

    def test_floor_validation(self):
        with self.assertRaises(common.Refused):
            lossless.run("out", "59328")


class ReplanAndEnqueue(unittest.TestCase):
    def row(self, cid, prints, ok=True):
        return {"candidate_id": cid, "old_digest": "d", "evidence_digest": "d", "release_product_id": 3,
                "considered_print_ids": prints, "guards": {"current_plan": ok}}

    def test_shared_print_and_eligibility(self):
        rows = [self.row(1, [10, 11]), self.row(2, [11, 12]), self.row(3, [13, 14]), self.row(4, [15, 16], ok=False)]
        out = replan.finish(rows, {}, "now", "1.3", rows)
        self.assertEqual([r["eligible"] for r in out["records"]], [False, False, True, False])
        self.assertEqual(out["summary"]["eligible"], 1)
        self.assertEqual(out["summary"]["guard_failures"], {"no_shared_print_with_other_planned": 2, "current_plan": 1})

    def test_approved_list_is_pinned_and_refuses_short(self):
        rows = [dict(self.row(i, [2 * i, 2 * i + 1]), eligible=True) for i in range(1, 4)]
        replanned = {"records": rows, "observed_at": "t", "resolver_version": "1.3"}
        data, sha, doc = replan.approved_list(replanned, 2)
        self.assertEqual(doc["expected_count"], 2)
        self.assertEqual(sha, replan.approved_list(replanned, 2)[1])
        import hashlib
        self.assertEqual(hashlib.sha256(data).hexdigest(), sha)
        with self.assertRaisesRegex(common.Refused, "only 3 eligible"):
            replan.approved_list(replanned, 4)

    def test_approved_list_sha_ignores_replan_time_not_digests(self):
        # The apply re-plans at a later time; an unchanged list must hash to the dry run's SHA.
        rows = [dict(self.row(i, [2 * i, 2 * i + 1]), eligible=True) for i in range(1, 3)]
        dry = replan.approved_list({"records": rows, "observed_at": "t1", "resolver_version": "1.3"}, 2)[1]
        later = replan.approved_list({"records": rows, "observed_at": "t2", "resolver_version": "1.3"}, 2)[1]
        self.assertEqual(dry, later)
        moved = [dict(rows[0], evidence_digest="d2"), rows[1]]
        self.assertNotEqual(dry, replan.approved_list({"records": moved, "observed_at": "t2", "resolver_version": "1.3"}, 2)[1])

    def test_apply_needs_the_dry_run_sha(self):
        enqueue_remaining.check_apply(False, "", "a" * 64)
        with self.assertRaisesRegex(common.Refused, "expected_sha256"):
            enqueue_remaining.check_apply(True, "", "a" * 64)
        with self.assertRaisesRegex(common.Refused, "differs"):
            enqueue_remaining.check_apply(True, "b" * 64, "a" * 64)
        enqueue_remaining.check_apply(True, "a" * 64, "a" * 64)

    def test_default_plan_loads(self):
        self.assertEqual(len(replan.load_plan()["records"]), 100)
        with self.assertRaises(common.Refused):
            replan.load_plan("/etc/passwd")


class FleetAndImages(unittest.TestCase):
    def test_receipt_path(self):
        self.assertTrue(fleet.receipt_path(None).is_file())
        for bad in ("../../etc/passwd", "docs/agent/STAGING_MISSION.json"):
            with self.assertRaises(common.Refused):
                fleet.receipt_path(bad)

    def test_compare(self):
        receipt = {"deployment_id": "d1", "image_digest": "sha256:x", "schedule_utc": "1 * * * *"}
        live = {"live_deployment": "d1", "live_digest": "sha256:x", "marker": True, "status": "SUCCESS",
                "schedule": "1 * * * *"}
        self.assertTrue(fleet.compare("c", receipt, live, [])["match"])
        self.assertFalse(fleet.compare("c", receipt, live, [{"id": "d2"}])["match"])
        self.assertFalse(fleet.compare("c", receipt, dict(live, live_digest="sha256:y"), [])["match"])
        self.assertFalse(fleet.compare("c", receipt, dict(live, schedule="2 * * * *"), [])["match"])

    def test_images_summary(self):
        node = {"cronSchedule": "15 7 * * *", "latestDeployment": {"id": "x", "status": "FAILED"}}
        out = official_images.summarize(node, [], {"healthy": True}, {"n": 1})
        self.assertTrue(out["latest_run_failed"])
        self.assertFalse(out["healthy"])
        node["latestDeployment"]["status"] = "SUCCESS"
        self.assertTrue(official_images.summarize(node, [], {"healthy": True}, {"n": 1})["healthy"])
        self.assertFalse(official_images.summarize(None, [], {}, {})["healthy"])

    def test_images_brief_dates_recent_runs(self):
        node = {"latestDeployment": {"id": "x", "status": "SUCCESS"}}
        recent = [{"id": "x", "status": "SUCCESS", "createdAt": "2026-10-16T07:15:02Z"}]
        result = official_images.summarize(node, recent, {"healthy": True}, {"n": 1})
        out = official_images.brief(result, {"healthy": True}, {"n": 1})
        self.assertEqual(out["recent_runs"], [{"status": "SUCCESS", "created_at": "2026-10-16T07:15:02Z"}])


class StagingStateSummary(unittest.TestCase):
    def snapshot(self, blockers):
        return {"verified_at": "t", "blockers": blockers, "evidence": {"sha256": "e"},
                "operational_health": {"yuyu": {"status": "HEALTHY"}}}

    def test_quarantine_count_and_age_in_summary(self):
        blockers = [{"id": "snkrdunk-identity-quarantine", "count": 23},
                    {"id": "quarantined-refresh-work", "scope": "s", "count": 69,
                     "oldest_blocked_since": "2026-10-02T15:54:00Z"}]
        out = staging_state.summary(self.snapshot(blockers), {"repository": {"sha": "h"}}, {"mission_actions": []})
        self.assertEqual(out["blockers"], ["snkrdunk-identity-quarantine", "quarantined-refresh-work"])
        self.assertEqual(out["quarantined_refresh_work"], {"count": 69, "oldest_blocked_since": "2026-10-02T15:54:00Z"})

    def test_no_quarantine_blocker(self):
        out = staging_state.summary(self.snapshot([]), {"repository": {"sha": "h"}}, {"mission_actions": []})
        self.assertIsNone(out["quarantined_refresh_work"])


if __name__ == "__main__":
    unittest.main()
