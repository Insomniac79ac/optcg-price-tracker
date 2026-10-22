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
from ops import capture_batch, collector_redeploy, common, diagnostic, enqueue_remaining, f1_approve, fleet, official_images, refresh_backfill, replan, run, staging_state, storage_rates  # noqa: E402
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

    def test_small_results_inline_in_summary(self):
        from datetime import datetime, timezone
        at = datetime(2026, 10, 16, 23, tzinfo=timezone.utc)
        result = {"work": {"rows": [{"work_id": 1, "state": "pending", "at": at}], "truncated": False},
                  "big": {"rows": [{"x": "y" * 100}] * 10, "truncated": False},
                  "empty": {"rows": [], "truncated": False}}
        out = diagnostic.inline(result, limit=200)
        self.assertEqual(out["rows"]["work"], {"columns": ["work_id", "state", "at"],
                                               "rows": [[1, "pending", at]]})
        self.assertEqual(out["rows"]["empty"], {"columns": [], "rows": []})
        self.assertEqual(out["rows_omitted"], ["big"])
        self.assertTrue(run.annotations({"result": out})[0].startswith("::notice title=ops-summary 1/1::"))

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

    def test_capture_population_sql_runs_read_only(self):
        import psycopg

        with psycopg.connect(self.dsn, options=ops_db.options()) as conn:
            self.assertEqual(conn.execute(capture_batch.POPULATION_SQL).fetchall(), [])


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


class CaptureBatch(unittest.TestCase):
    def plan(self, status, prints, release=7, reasons=()):
        return SimpleNamespace(resolution_status=status, release_product_id=release, card_code="OP01-001",
                               evidence_digest="d", resolution_reasons=reasons,
                               alternatives=[SimpleNamespace(card_print_id=i) for i in prints])

    def test_shortlist_keeps_every_bounded_ambiguous_family_in_order(self):
        plans = {1: self.plan("exact", [10], reasons=("unique_listing_kind_resolves_one_release_sibling",)),
                 2: self.plan("ambiguous", [12, 11]),
                 3: self.plan("ambiguous", list(range(20, 33))),  # 13 siblings
                 4: self.plan("ambiguous", [40, 41], release=None),
                 6: self.plan("ambiguous", [60, 61]),
                 7: self.plan("ambiguous", [70, 71]),
                 8: self.plan("release_unresolved", [])}
        records, dropped = capture_batch.shortlist([1, 2, 3, 4, 5, 6, 7, 8], plans)
        self.assertEqual([r["candidate_id"] for r in records], [2, 6, 7])  # not cut off by any batch size
        self.assertEqual(records[0]["considered_print_ids"], [11, 12])
        self.assertEqual(dropped, {"exact_now:unique_listing_kind_resolves_one_release_sibling": 1, "no_current_plan": 1,
                                   "unbounded_siblings": 1, "no_release": 1, "resolved_since:release_unresolved": 1})

    def row(self, cid, prints, **failed):
        guards = {"current_plan": True, "no_active_yuyu_mapping": True, **{k: False for k in failed}}
        return {"candidate_id": cid, "evidence_digest": "d", "old_digest": "d", "release_product_id": 3,
                "considered_print_ids": prints, "guards": guards}

    def test_shared_print_guard_runs_in_plan_order(self):
        rows = capture_batch.choose([self.row(1, [1, 2]), self.row(2, [2, 3]), self.row(3, [4, 5], no_active_yuyu_mapping=1),
                                     self.row(4, [5, 6]), self.row(5, [7, 8])])
        self.assertEqual([r["eligible"] for r in rows], [True, False, False, True, True])
        # Row 4 shares print 5 only with row 3, which is ineligible, so it is not held.
        self.assertEqual(capture_batch.first_failed_guards(rows), {capture_batch.SHARED: 1, "no_active_yuyu_mapping": 1})

    def judged(self, rows, limit):
        """replan_all over rows standing in for evaluate_candidate, without a database."""
        session = SimpleNamespace(execute=lambda *a, **k: SimpleNamespace(scalar=lambda: utc(2026, 10, 19, 13)),
                                  rollback=lambda: None)
        by_id = {r["candidate_id"]: r for r in rows}
        plan = {"observed_at": "t", "records": [{"candidate_id": r["candidate_id"]} for r in rows]}
        with mock.patch.object(replan, "evaluate_candidate", lambda s, rec: json.loads(json.dumps(by_id[rec["candidate_id"]]))):
            return capture_batch.replan_all(session, plan, limit=limit, resolver_version="t")

    def test_stopping_at_count_gives_the_same_batch_as_judging_all(self):
        rows = [self.row(1, [1, 2]), self.row(2, [2, 3]), self.row(3, [4]), self.row(4, [5], current_plan=1),
                self.row(5, [6]), self.row(6, [7])]
        full, early = self.judged(rows, None), self.judged(rows, 2)
        self.assertEqual(full["summary"]["eligible"], 4)
        self.assertEqual(early["summary"]["eligible"], 2)
        self.assertEqual(early["plan"]["judged"], 3)
        for size in (1, 2):
            self.assertEqual(replan.approved_list(full, size, batch=f"capture-{size}")[1],
                             replan.approved_list(early, size, batch=f"capture-{size}")[1])

    def deliver(self, eligible, count, **kw):
        rows = capture_batch.choose([self.row(i, [2 * i, 2 * i + 1]) for i in range(1, eligible + 1)]
                                    + [self.row(99, [990], no_active_yuyu_mapping=1)])
        replanned = replan.summarize(rows, {}, "t", "1.3", rows)
        plan = {"records": [{"candidate_id": r["candidate_id"], "card_code": f"C{r['candidate_id']}"} for r in rows]}
        seen = {}

        def enqueue_list(out, replanned, size, *, apply, expected_sha256, batch):
            data, sha, doc = replan.approved_list(replanned, size, batch=batch)
            (out / "approved-list.json").write_bytes(data)
            enqueue_remaining.check_apply(apply, expected_sha256, sha)
            seen.update(size=size, batch=batch)
            return {"status": "DRY_RUN_OK", "approved_list_sha256": sha}

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(enqueue_remaining, "enqueue_list", enqueue_list):
            result = capture_batch.deliver(Path(tmp), plan, replanned, {"eligible": eligible}, count, **kw)
        return result, seen

    def test_count_means_up_to(self):
        result, seen = self.deliver(9, 12, apply=False, expected_sha256="")
        self.assertEqual((result["requested"], result["batch_size"], seen["batch"]), (12, 9, "capture-9"))
        self.assertEqual([b[0] for b in result["batch"]], list(range(1, 10)))
        result, seen = self.deliver(30, 12, apply=False, expected_sha256="")
        self.assertEqual((result["batch_size"], seen["size"]), (12, 12))

    def test_refuses_only_when_nothing_is_eligible(self):
        result, seen = self.deliver(0, 12, apply=False, expected_sha256="")
        self.assertEqual((result["status"], result["batch_size"], seen), ("REFUSED", 0, {}))
        self.assertIn("breakdown", result)  # the refusal keeps the reasons
        for eligible in (1, 5):
            self.assertEqual(self.deliver(eligible, 50, apply=False, expected_sha256="")[0]["batch_size"], eligible)

    def test_apply_refuses_only_on_sha_mismatch(self):
        dry, _ = self.deliver(9, 12, apply=False, expected_sha256="")
        applied, _ = self.deliver(9, 12, apply=True, expected_sha256=dry["approved_list_sha256"])
        self.assertEqual(applied["batch_size"], 9)
        with self.assertRaisesRegex(common.Refused, "differs from the dry run"):
            self.deliver(8, 12, apply=True, expected_sha256=dry["approved_list_sha256"])  # one candidate gone
        with self.assertRaisesRegex(common.Refused, "differs from the dry run"):
            self.deliver(9, 12, apply=True, expected_sha256="0" * 64)

    def test_count_limits(self):
        self.assertEqual(capture_batch.check_count(None), 50)
        for bad in (0, 101, "50"):
            with self.assertRaises(common.Refused):
                capture_batch.check_count(bad)

    def test_batch_label_is_in_the_pinned_list(self):
        rows = [{"candidate_id": i, "evidence_digest": "d", "release_product_id": 3, "considered_print_ids": [2 * i, 2 * i + 1],
                 "eligible": True} for i in range(1, 3)]
        replanned = {"records": rows, "observed_at": "t", "resolver_version": "1.3"}
        self.assertEqual(replan.approved_list(replanned, 2)[2]["batch"], "NEW2")  # enqueue-remaining-50 unchanged
        _, sha, doc = replan.approved_list(replanned, 2, batch="capture-2")
        self.assertEqual(doc["batch"], "capture-2")
        self.assertNotEqual(sha, replan.approved_list(replanned, 2)[1])

    def test_population_sql_is_read_only_and_names_each_exclusion(self):
        sql = capture_batch.POPULATION_SQL.lower()
        self.assertTrue(sql.strip().startswith("select"))
        for word in ("insert", "update", "delete", "for update"):
            self.assertNotIn(word, sql)
        self.assertIn("yuyu-identity:", sql)
        self.assertIn("reviewed_at is not null", sql)
        for reason in ("reviewed_decision", "capture_blocked", "already_captured", "capture_queued", "uncaptured"):
            self.assertIn(f"'{reason}'", sql)

    def test_preview_is_a_read_runbook_in_ops_readonly(self):
        self.assertEqual(run.RUNBOOKS["capture-batch-preview"][:2], ("read", False))
        args = SimpleNamespace(runbook="capture-batch-preview", workflow="ops-readonly", apply=False)
        run.preflight(args, now=utc(2026, 10, 19, 3), read=lambda path: {"workflow_runs": []})
        with self.assertRaises(common.Refused):
            run.preflight(SimpleNamespace(**(vars(args) | {"apply": True})), now=utc(2026, 10, 19, 12), read=None)

    def test_apply_respects_windows_and_ops_write(self):
        args = SimpleNamespace(runbook="enqueue-capture-batch", workflow="ops-write", apply=True)
        idle = lambda path: {"workflow_runs": []}  # noqa: E731
        for hour, minute in ((2, 30), (19, 45)):
            with self.assertRaises(common.Refused):
                run.preflight(args, now=utc(2026, 10, 19, hour, minute), read=idle)
        run.preflight(args, now=utc(2026, 10, 19, 12), read=idle)
        with self.assertRaises(common.Refused):
            run.preflight(SimpleNamespace(**(vars(args) | {"workflow": "ops-readonly"})), now=utc(2026, 10, 19, 12), read=idle)


class F1Approve(unittest.TestCase):
    def entry(self, gid, digest="d" * 64):
        return {"proposal_group_id": gid, "selected_alternative_id": gid * 10, "source_candidate_id": gid + 1000,
                "card_print_id": gid + 5000, "evidence_digest": digest, "resolver_version": "1.4",
                "updated_at": "2026-10-18T14:00:00+00:00", "detail": {"listing_title": f"t{gid}"}}

    def test_list_is_pinned_on_decision_fields_only(self):
        rows = [self.entry(i) for i in range(1, 6)]
        data, sha, doc = f1_approve.pinned_list(rows, 3)
        import hashlib
        self.assertEqual(hashlib.sha256(data).hexdigest(), sha)
        self.assertEqual([e["proposal_group_id"] for e in doc["entries"]], [1, 2, 3])
        self.assertEqual(doc["expected_count"], 3)
        self.assertNotIn("detail", doc["entries"][0])
        relabelled = [dict(r, detail={"listing_title": "other"}) for r in rows]
        self.assertEqual(sha, f1_approve.pinned_list(relabelled, 3)[1])
        moved = [rows[0], dict(rows[1], evidence_digest="e" * 64)] + rows[2:]
        self.assertNotEqual(sha, f1_approve.pinned_list(moved, 3)[1])
        # Fewer eligible than asked: the batch is what is there (the last batch is short).
        self.assertEqual(f1_approve.pinned_list(rows, 500)[2]["expected_count"], 5)
        with self.assertRaisesRegex(common.Refused, "no eligible"):
            f1_approve.pinned_list([], 500)

    def test_sample_is_reproducible(self):
        rows = [self.entry(i) for i in range(1, 501)]
        sha = f1_approve.pinned_list(rows, 500)[1]
        picked = f1_approve.sample(rows, sha)
        self.assertEqual(len(picked), 20)
        self.assertEqual(picked, f1_approve.sample(rows, sha))
        self.assertEqual(len({r["proposal_group_id"] for r in picked}), 20)
        self.assertEqual(len(f1_approve.sample(rows[:7], sha)), 7)

    def test_count_and_apply_guards(self):
        self.assertEqual(f1_approve.check_count(None), 500)
        for bad in (0, 601):
            with self.assertRaises(common.Refused):
                f1_approve.check_count(bad)
        f1_approve.check_apply(False, "", "a" * 64)
        with self.assertRaisesRegex(common.Refused, "expected_sha256"):
            f1_approve.check_apply(True, "A" * 64, "a" * 64)
        with self.assertRaisesRegex(common.Refused, "differs"):
            f1_approve.check_apply(True, "b" * 64, "a" * 64)
        f1_approve.check_apply(True, "a" * 64, "a" * 64)

    def test_apply_respects_windows_and_ops_write(self):
        args = SimpleNamespace(runbook="approve-f1-batch", workflow="ops-write", apply=True)
        idle = lambda path: {"workflow_runs": []}  # noqa: E731
        for hour in (2, 5):
            with self.assertRaisesRegex(common.Refused, "collector quiet window"):
                run.preflight(args, now=utc(2026, 10, 19, hour, 10), read=idle)
        run.preflight(args, now=utc(2026, 10, 19, 12), read=idle)
        with self.assertRaises(common.Refused):
            run.preflight(SimpleNamespace(**(vars(args) | {"workflow": "ops-readonly"})), now=utc(2026, 10, 19, 12), read=idle)

    def test_approve_one_transaction_each_and_stops_at_first_refusal(self):
        from app.services.source_mapping_proposal_decision import ProposalDecisionError

        calls = []

        def fake(db, gid, request, actor):
            calls.append((gid, request.selected_alternative_id, actor.email))
            if gid == 3:
                raise ProposalDecisionError("evidence_digest_changed", "moved")
            return SimpleNamespace(proposal_group_id=gid, resulting_source_card_mapping_id=gid + 90,
                                   card_print_id=gid + 5000, mapping_created=True)

        session = mock.Mock()
        entries = f1_approve.pinned_list([self.entry(i) for i in range(1, 6)], 5)[2]["entries"]
        with mock.patch("app.services.source_mapping_proposal_decision.approve_exact_proposal", fake):
            approved, stopped = f1_approve.approve(session, entries, run_label="ops-write:approve-f1-batch:1",
                                                   now=lambda: utc(2026, 10, 19, 12))
        self.assertEqual([a["proposal_group_id"] for a in approved], [1, 2])
        self.assertEqual(stopped["code"], "evidence_digest_changed")
        self.assertEqual([c[0] for c in calls], [1, 2, 3])
        self.assertEqual(session.commit.call_count, 2)
        self.assertEqual(session.rollback.call_count, 1)
        self.assertEqual(calls[0][2], "ops-write:approve-f1-batch:1")

    def test_approve_stops_before_the_collector_quiet_window(self):
        session = mock.Mock()
        entries = f1_approve.pinned_list([self.entry(1)], 1)[2]["entries"]
        with mock.patch("app.services.source_mapping_proposal_decision.approve_exact_proposal") as fake:
            approved, stopped = f1_approve.approve(session, entries, run_label="x", now=lambda: utc(2026, 10, 19, 2, 1))
        fake.assert_not_called()
        self.assertEqual((approved, stopped["code"]), ([], "quiet_window"))


class RefreshBackfill(unittest.TestCase):
    def row(self, mid, source="yuyutei"):
        return {"mapping_id": mid, "source": source, "card_print_id": mid + 5000,
                "listing_identity": f"yuyutei:op01:{mid}", "source_url": f"https://yuyu-tei.jp/{mid}",
                "card_code": "OP01-001", "rarity": "R", "variant": "base"}

    def rates(self):
        return {"variants": {"ex_steps": {"planning_mb_day_s9": 32.0}}, "room_to_reserve_mb_s9": 2800.0}

    def test_list_is_pinned_on_decision_fields_only(self):
        rows = [self.row(i) for i in range(1, 6)]
        _, sha, doc = refresh_backfill.pinned_list(rows, 3)
        self.assertEqual([e["mapping_id"] for e in doc["entries"]], [1, 2, 3])
        self.assertEqual(set(doc["entries"][0]), set(refresh_backfill.LIST_KEYS))
        moved = [dict(r, source_url="https://elsewhere") for r in rows]
        self.assertEqual(refresh_backfill.pinned_list(moved, 3)[1], sha)  # display fields are not pinned
        self.assertNotEqual(refresh_backfill.pinned_list(rows[1:], 3)[1], sha)  # a new row changes it
        self.assertEqual(refresh_backfill.sample(rows, sha), refresh_backfill.sample(rows, sha))
        with self.assertRaises(common.Refused):
            refresh_backfill.pinned_list([], 3)

    def test_apply_refuses_without_or_on_a_different_sha(self):
        sha = refresh_backfill.pinned_list([self.row(1)], 5)[1]
        refresh_backfill.check_apply(False, "", sha)
        refresh_backfill.check_apply(True, sha, sha)
        for bad in ("", "xyz", "0" * 64):
            with self.assertRaises(common.Refused):
                refresh_backfill.check_apply(True, bad, sha)

    def test_sha_mismatch_refuses_before_any_write_session(self):
        rows = [self.row(1), self.row(2, "snkrdunk")]
        with tempfile.TemporaryDirectory() as out, \
                mock.patch.object(refresh_backfill, "unplanned", return_value=(rows, 10)), \
                mock.patch.object(refresh_backfill, "plan") as plan, \
                mock.patch("ops.db.engine"), mock.patch("sqlalchemy.orm.Session"), \
                mock.patch("yuyu_identity_capture_enqueue.staging_session") as writable:
            with self.assertRaises(common.Refused):
                refresh_backfill.run(out, apply=True, expected_sha256="0" * 64)
            plan.assert_not_called()
            writable.assert_not_called()

    def test_dry_run_summary_and_storage_estimate(self):
        rows = [self.row(1), self.row(2), self.row(3, "snkrdunk")]
        with tempfile.TemporaryDirectory() as out, \
                mock.patch.object(refresh_backfill, "unplanned", return_value=(rows, 2000)), \
                mock.patch("ops.db.engine"), mock.patch("sqlalchemy.orm.Session"), \
                mock.patch.object(storage_rates, "load_events", return_value={"window_start": "x"}), \
                mock.patch.object(storage_rates, "fetch_series"), \
                mock.patch.object(storage_rates, "compute", return_value=self.rates()):
            summary = refresh_backfill.run(out, count=2)
            self.assertTrue((Path(out) / "backfill-list.json").is_file())
        self.assertEqual(summary["status"], "DRY_RUN_OK")
        self.assertEqual((summary["batch_size"], summary["unplanned_total"], summary["written"]), (2, 3, 0))
        self.assertEqual(summary["by_source"], {"yuyutei": 2})
        storage = summary["storage"]
        self.assertEqual(storage["label"], "ESTIMATE")
        self.assertEqual(storage["mb_day_per_refresh_row"], 0.016)
        self.assertEqual(storage["added_mb_day"], 0.03)
        self.assertEqual(storage["days_to_reserve_now"], 87.5)

    def test_count_limits_and_read_only_sql(self):
        self.assertEqual(refresh_backfill.check_count(None), 500)
        for bad in (0, 1001, "5"):
            with self.assertRaises(common.Refused):
                refresh_backfill.check_count(bad)
        for sql in (refresh_backfill.UNPLANNED_SQL, refresh_backfill.PLANNED_SQL):
            low = sql.lower()
            self.assertTrue(low.strip().startswith("with"))
            for word in ("insert", "update", "delete", "for update"):
                self.assertNotIn(word, low)

    def test_registered_as_collector_affecting_write(self):
        self.assertEqual(run.RUNBOOKS["plan-refresh-backfill"][:2], ("write", True))
        self.assertEqual(run.kind_of("plan-refresh-backfill", False), (False, False))


class CollectorRedeploy(unittest.TestCase):
    def test_registered_as_collector_affecting_write(self):
        self.assertEqual(run.RUNBOOKS["collector-redeploy"][:2], ("write", True))
        self.assertEqual(run.kind_of("collector-redeploy", True), (True, True))
        args = SimpleNamespace(runbook="collector-redeploy", workflow="ops-readonly", apply=False)
        with self.assertRaisesRegex(common.Refused, "ops-write"):
            run.preflight(args, read=None)
        args = SimpleNamespace(runbook="collector-redeploy", workflow="ops-write", apply=True)
        with self.assertRaisesRegex(common.Refused, "02:00-06:00"):
            run.preflight(args, now=utc(2026, 10, 22, 3), read=lambda path: {})

    def test_count_refused(self):
        args = SimpleNamespace(count=5, apply=False, expected_sha256="")
        with self.assertRaisesRegex(common.Refused, "no count"):
            run._collector_redeploy(args, "out")

    def test_pins_come_from_the_fleet_state(self):
        import collector_variables as cv
        fleet_state = json.loads((ROOT / "docs/agent/STAGING_FLEET.json").read_text())["deployment_verification"]
        pins = collector_redeploy.fleet_pins(cv.delivery.NAMES)
        self.assertEqual(len(pins), 10)
        self.assertEqual(pins["snkrdunk-collector"], fleet_state["snkr_component"])
        for name, commit in pins.items():
            if name != "snkrdunk-collector":
                self.assertEqual(commit, fleet_state["yuyu_reader_component"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / collector_redeploy.FLEET
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"deployment_verification": dict(fleet_state, snkr_component="merge")}))
            with self.assertRaisesRegex(common.Refused, "snkrdunk-collector: no full commit pin"):
                collector_redeploy.fleet_pins(cv.delivery.NAMES, root=tmp)

    def test_pinned_source_is_the_newest_redeployable_copy_of_the_pin(self):
        class Mismatch(Exception):
            pass

        image = "sha256:" + "b" * 64
        rows = {
            "new-other-commit": None,  # marker of another commit: read refuses
            "new-no-image": {"id": "new-no-image", "canRedeploy": True, "meta": {}},  # SKIPPED record
            "pinned-not-redeployable": {"id": "pinned-not-redeployable", "canRedeploy": False,
                                        "meta": {"imageDigest": image}},
            "pinned": {"id": "pinned", "canRedeploy": True, "meta": {"imageDigest": image}},
            "older-pinned": {"id": "older-pinned", "canRedeploy": True, "meta": {"imageDigest": image}},
        }

        def read(identity, service_id, commit):
            if rows[identity] is None:
                raise Mismatch("Uploaded deployment destination/source mismatch")
            return rows[identity]

        found = collector_redeploy.pinned_source({"serviceId": "s"}, "c" * 40, read=read,
                                                 listing=lambda sid: list(rows), error=Mismatch)
        self.assertEqual(found["id"], "pinned")
        with self.assertRaisesRegex(Mismatch, "No redeployable deployment of the pinned commit"):
            collector_redeploy.pinned_source({"serviceId": "s"}, "c" * 40, read=read,
                                             listing=lambda sid: ["new-other-commit"], error=Mismatch)

    def test_plan_uses_the_pin_and_the_source_digest(self):
        import generate_staging_state as state
        pins = {"snkrdunk-collector": "f" * 40, "yuyutei-collector-shard-0": "2" * 40}
        live = {n: {"serviceId": "svc-" + n, "cronSchedule": "1 * * * *",
                    "latestDeployment": {"id": "live-" + n, "status": "FAILED"}} for n in pins}

        def source(node, commit):
            if node["serviceId"] == "svc-yuyutei-collector-shard-0":
                raise state.VerificationError("No redeployable deployment of the pinned commit")
            return {"id": "src-" + commit[:4], "meta": {"imageDigest": "sha256:" + "d" * 64}}

        rows = {r["service"]: r for r in collector_redeploy.plan(live, pins, source)}
        self.assertEqual(rows["snkrdunk-collector"]["commit"], "f" * 40)
        self.assertEqual(rows["snkrdunk-collector"]["source_deployment"], "src-ffff")
        self.assertEqual(rows["snkrdunk-collector"]["image_digest"], "sha256:" + "d" * 64)
        self.assertIsNone(rows["yuyutei-collector-shard-0"]["source_deployment"])
        self.assertIn("pinned commit", rows["yuyutei-collector-shard-0"]["problem"])
        live.pop("yuyutei-collector-shard-0")
        with self.assertRaisesRegex(common.Refused, "shard-0: service not found"):
            collector_redeploy.plan(live, pins, source)

    def test_plan_sha_pins_the_live_deployment(self):
        row = {"service": "s", "commit": "c" * 40, "image_digest": "sha256:" + "a" * 64, "live_deployment": "d1"}
        sha = collector_redeploy.plan_sha([row])
        self.assertNotEqual(sha, collector_redeploy.plan_sha([dict(row, live_deployment="d2")]))
        collector_redeploy.check_apply(False, "", sha)
        collector_redeploy.check_apply(True, sha, sha)
        for bad in ("", "x" * 64, "0" * 64):
            with self.assertRaises(common.Refused):
                collector_redeploy.check_apply(True, bad, sha)

    def test_apply_redeploys_in_order_and_stops_at_first_failure(self):
        import generate_staging_state as state
        rows = [{"service": n, "commit": "c" * 40, "image_digest": "sha256:" + "a" * 64,
                 "live_deployment": "old-" + n} for n in ("a", "b", "c")]
        calls = []

        def restore(name, values, commit, digest):
            calls.append((name, values, commit, digest))
            if name == "b":
                raise state.VerificationError("Restore failed: Redeployed image differs from the verified upload")
            return {"source_deployment": "src-" + name, "deployment": "new-" + name, "image_digest": digest,
                    "observed_at": "t"}

        done, stopped = collector_redeploy.apply_rows(rows, restore, now=lambda: utc(2026, 10, 22, 9))
        self.assertEqual([c[0] for c in calls], ["a", "b"])
        self.assertEqual(calls[0][1], {"APP_ENV": "staging"})
        self.assertEqual([d["deployment"] for d in done], ["new-a"])
        self.assertEqual(stopped["service"], "b")
        self.assertIn("image differs", stopped["reason"])

    def test_apply_stops_before_the_collector_quiet_window(self):
        rows = [{"service": "a", "commit": "c", "image_digest": "d", "live_deployment": "x"}]
        done, stopped = collector_redeploy.apply_rows(rows, lambda *a: self.fail("ran"),
                                                      now=lambda: utc(2026, 10, 22, 2, 30))
        self.assertEqual(done, [])
        self.assertIn("02:00-06:00", stopped["reason"])

    def test_noop_value_is_an_allowed_collector_variable(self):
        import collector_variables as cv
        self.assertEqual(cv.parse_assignments([f"{k}={v}" for k, v in collector_redeploy.NOOP.items()]),
                         collector_redeploy.NOOP)


class FleetAndImages(unittest.TestCase):
    def test_receipt_path(self):
        self.assertTrue(fleet.receipt_path(None).is_file())
        for bad in ("../../etc/passwd", "docs/agent/STAGING_MISSION.json"):
            with self.assertRaises(common.Refused):
                fleet.receipt_path(bad)

    def test_default_receipt_chain(self):
        receipts = fleet.load_receipts(None)
        self.assertEqual([d["source_sha"][:7] for _, d in receipts], ["a504e47", "2bcbe90"])
        owners = {n: fleet.receipt_for(n, receipts)[1]["source_sha"][:7]
                  for n in receipts[0][1]["deployments"]}
        self.assertEqual(len(owners), 10)
        self.assertEqual(owners["snkrdunk-collector"], "a504e47")
        self.assertEqual(sorted(n for n, c in owners.items() if c == "2bcbe90"),
                         sorted(receipts[1][1]["deployments"]))
        self.assertEqual(len(receipts[1][1]["deployments"]), 9)
        self.assertIsNone(fleet.receipt_for("not-a-collector", receipts))
        with self.assertRaises(common.Refused):
            fleet.load_receipts(fleet.DEFAULT_RECEIPTS[0] + ",docs/agent/STAGING_MISSION.json")

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
