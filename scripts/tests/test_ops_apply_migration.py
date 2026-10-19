"""ops-write runbook apply-migration: allowlist, backup and live-revision refusals, one transaction.

Offline except ApplyMigrationOnPostgres, which needs OPS_TEST_POSTGRES_URL (CI sets it and
REQUIRE_POSTGRES=1). Both run a throwaway Alembic script directory carrying the allowlisted
revision ids, never the real migration, and the Postgres tests work in a schema of their own.
"""
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
from ops import apply_migration as am, common, run  # noqa: E402
from ops import db as ops_db  # noqa: E402

REV, PARENT = "7a52e9b48e8a", "3b7d9c1a5e20"
FRESH = {"id": "backup-1", "created_at": "2026-10-19T03:00:00Z", "age_hours": 2.5}
STEP = '''    op.create_table("am_new", sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("old_id", sa.Integer, sa.ForeignKey("am_old.id")))
    op.add_column("am_old", sa.Column("grade", sa.String(8)))
    op.execute("ALTER TABLE am_old ADD CONSTRAINT ck_am_old_grade CHECK (grade IS NULL OR grade <> '') NOT VALID")
    op.execute("ALTER TABLE am_old VALIDATE CONSTRAINT ck_am_old_grade")
    op.execute("INSERT INTO am_old (id) VALUES (100)")
'''
# Fails on its last statement, after DDL already ran: everything must roll back.
FAILING = STEP + '''    op.execute("INSERT INTO am_old (id) VALUES (1)")
'''


def scripts(tmp, body=STEP, revision=REV, parent=PARENT, extra_head=False):
    from alembic.script import ScriptDirectory

    versions = Path(tmp) / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    head = 'branch_labels = None\ndepends_on = None\n'
    (versions / "base.py").write_text(
        f'revision = "{PARENT}"\ndown_revision = None\n{head}def upgrade():\n    pass\n')
    (versions / "step.py").write_text(
        f'from alembic import op\nimport sqlalchemy as sa\nrevision = "{revision}"\n'
        f'down_revision = "{parent}"\n{head}def upgrade():\n{body}')
    if extra_head:
        (versions / "other.py").write_text(
            f'revision = "0000000000aa"\ndown_revision = "{PARENT}"\n{head}def upgrade():\n    pass\n')
    return ScriptDirectory(str(tmp))


def no_engine(**_):
    raise AssertionError("no database may be opened before the inputs are accepted")


class Refusals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "out"
        self.out.mkdir()
        self.script = scripts(Path(self.tmp.name) / "alembic")

    def run_am(self, **kwargs):
        kwargs = {"revision": REV, "parent": PARENT, "backup": lambda: FRESH,
                  "engine_factory": no_engine, "script": self.script, **kwargs}
        return am.run(self.out, **kwargs)

    def test_only_the_allowlisted_pair(self):
        self.assertEqual(am.ALLOWED, {REV: PARENT})
        am.check_pair(REV, PARENT)
        for revision, parent, why in ((PARENT, "", "not allowlisted"), ("", PARENT, "not allowlisted"),
                                      ("7a52e9b48e8b", PARENT, "not allowlisted"),
                                      (REV, "", "applies only on parent"),
                                      (REV, "3b7d9c1a5e21", "applies only on parent"), (REV, REV, "applies only")):
            with self.subTest(revision=revision, parent=parent), self.assertRaisesRegex(common.Refused, why):
                self.run_am(revision=revision, parent=parent)

    def test_checkout_must_carry_the_migration_as_only_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = scripts(tmp, revision="0000000000bb")
            with self.assertRaisesRegex(common.Refused, "not in this checkout"):
                am.check_checkout(missing, REV, PARENT)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "versions").mkdir()
            (Path(tmp) / "versions/cc.py").write_text(
                'revision = "0000000000cc"\ndown_revision = None\nbranch_labels = None\ndepends_on = None\n')
            with self.assertRaisesRegex(common.Refused, "revises 0000000000cc"):
                am.check_checkout(scripts(tmp, parent="0000000000cc"), REV, PARENT)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(common.Refused, "heads are"):
                am.check_checkout(scripts(tmp, extra_head=True), REV, PARENT)
        am.check_checkout(self.script, REV, PARENT)

    def test_backup_missing_or_stale(self):
        with self.assertRaisesRegex(common.Refused, "no Railway backup.*Backups"):
            self.run_am(backup=lambda: None)
        for age in (24, 24.01, 30, -1, None, "2"):
            with self.subTest(age=age), self.assertRaisesRegex(common.Refused, "needs under 24 h.*Backups"):
                self.run_am(backup=lambda age=age: {**FRESH, "age_hours": age})
        self.assertEqual(am.check_backup({**FRESH, "age_hours": 23.99})["age_hours"], 23.99)

    def test_live_revision(self):
        with self.assertRaisesRegex(common.Refused, "already applied"):
            am.check_live((REV,), REV, PARENT)
        for live in ((), ("0000000000aa",), (PARENT, REV)):
            with self.subTest(live=live), self.assertRaisesRegex(common.Refused, "not parent"):
                am.check_live(live, REV, PARENT)
        am.check_live((PARENT,), REV, PARENT)

    def test_apply_needs_the_dry_run_sha(self):
        sql, sha = am.sql_plan(self.script, REV, PARENT)
        self.assertEqual(am.sql_plan(self.script, REV, PARENT)[1], sha)
        for bad in ("", "0" * 64, sha.upper(), sha[:-1]):
            with self.subTest(bad=bad), self.assertRaisesRegex(common.Refused, "expected_sha256"):
                self.run_am(apply=True, expected_sha256=bad)
        self.assertEqual((self.out / "migration-plan.sql").read_text(), sql)

    def test_plan_locks(self):
        sql, _ = am.sql_plan(self.script, REV, PARENT)
        self.assertIn("UPDATE alembic_version SET version_num='7a52e9b48e8a'", sql)
        self.assertNotIn("CREATE TABLE alembic_version", sql)
        existing, new = am.locks(sql)
        self.assertEqual(new, ["am_new"])
        self.assertEqual(existing["am_old"], ["ACCESS EXCLUSIVE", "SHARE UPDATE EXCLUSIVE (full scan)",
                                              "ROW EXCLUSIVE", "SHARE ROW EXCLUSIVE (new foreign key)"])
        self.assertEqual(existing["alembic_version"], ["ROW EXCLUSIVE"])
        budget = am.lock_budget(existing)
        self.assertEqual(budget["access_exclusive_until_commit"], ["am_old"])
        self.assertTrue(budget["one_transaction"])

    def test_fingerprint_ignores_only_the_revision_check(self):
        checks = [SimpleNamespace(name="fingerprint D - alembic revision", ok=False),
                  SimpleNamespace(name="fingerprint A - database", ok=True)]
        guard = SimpleNamespace(collect_facts=lambda raw: "facts", evaluate=mock.Mock(return_value=checks))
        raw = mock.Mock()
        engine = SimpleNamespace(raw_connection=lambda: raw)
        am.fingerprint(engine, guard, PARENT)
        guard.evaluate.assert_called_once_with("facts", frozenset({PARENT}))
        checks[1].ok = False
        with self.assertRaisesRegex(common.Refused, "fingerprint A"):
            am.fingerprint(engine, guard, PARENT)

    def test_only_the_writable_engine_drops_read_only(self):
        proxy = {"domain": "h.invalid", "proxyPort": 1}
        seen = []

        def connect(**kwargs):
            seen.append(kwargs["options"])
            raise OSError("no network in tests")
        for writable in (False, True):
            variables = {"PGUSER": "u", "PGPASSWORD": "p", "PGDATABASE": "d"}
            with mock.patch.object(ops_db, "resolve", return_value=(proxy, variables)), \
                    mock.patch("psycopg.connect", side_effect=connect):
                engine, _ = am.staging_engine(writable=writable)
                with self.assertRaisesRegex(common.Refused, "connection failed"):
                    engine.connect()
            self.assertEqual(variables, {})  # credentials do not outlive the engine setup
        self.assertIn(ops_db.READ_ONLY_OPTION, seen[0])
        self.assertNotIn("read_only", seen[1])
        self.assertIn("statement_timeout=120000", seen[1])

    def test_registered_write_runbook_with_preflight_allowlist(self):
        self.assertEqual(run.RUNBOOKS["apply-migration"][:2], ("write", True))
        args = SimpleNamespace(runbook="apply-migration", workflow="ops-write", apply=False,
                               revision=REV, parent="0000000000aa")
        with self.assertRaisesRegex(common.Refused, "applies only on parent"):
            run.preflight(args, now=common.now_utc(), read=None)
        args.workflow = "ops-readonly"
        with self.assertRaisesRegex(common.Refused, "ops-write"):
            run.preflight(args, read=None)

    def test_workflow_passes_revision_and_parent_to_both_jobs(self):
        text = (ROOT / ".github/workflows/ops-write.yml").read_text()
        approval, runbook = text.split("\n  runbook:\n")
        for job in (approval, runbook):
            self.assertIn("REVISION: ${{ inputs.revision }}", job)
            self.assertIn('args+=(--revision "$REVISION")', job)
            self.assertIn('args+=(--parent "$PARENT")', job)


@unittest.skipUnless(os.environ.get("OPS_TEST_POSTGRES_URL") or os.environ.get("REQUIRE_POSTGRES"),
                     "OPS_TEST_POSTGRES_URL not set")
class ApplyMigrationOnPostgres(unittest.TestCase):
    SCHEMA = "ops_apply_migration_test"

    @classmethod
    def setUpClass(cls):
        url = os.environ.get("OPS_TEST_POSTGRES_URL")
        if not url:
            raise AssertionError("REQUIRE_POSTGRES=1 but OPS_TEST_POSTGRES_URL is not set")
        cls.url = url

    def setUp(self):
        import sqlalchemy as sa

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "out"
        self.out.mkdir()
        admin = sa.create_engine(self.url, poolclass=sa.pool.NullPool)
        with admin.begin() as conn:
            conn.exec_driver_sql(f"drop schema if exists {self.SCHEMA} cascade")
            conn.exec_driver_sql(f"create schema {self.SCHEMA}")
            conn.exec_driver_sql(f"set local search_path = {self.SCHEMA}")
            conn.exec_driver_sql("create table am_old (id int primary key)")
            conn.exec_driver_sql("insert into am_old values (1), (2), (3)")
            conn.exec_driver_sql("create table alembic_version (version_num varchar(32) primary key)")
            conn.exec_driver_sql(f"insert into alembic_version values ('{PARENT}')")
        admin.dispose()
        self.addCleanup(self.drop_schema)
        self.writable_opened = 0

    def drop_schema(self):
        import sqlalchemy as sa

        admin = sa.create_engine(self.url, poolclass=sa.pool.NullPool)
        with admin.begin() as conn:
            conn.exec_driver_sql(f"drop schema if exists {self.SCHEMA} cascade")
        admin.dispose()

    def engine(self, *, writable):
        import sqlalchemy as sa

        options = f"-c search_path={self.SCHEMA}"
        if writable:
            self.writable_opened += 1
        else:
            options += " " + ops_db.READ_ONLY_OPTION
        return sa.create_engine(self.url, connect_args={"options": options}, poolclass=sa.pool.NullPool), None

    def state(self):
        engine, _ = self.engine(writable=False)
        with engine.connect() as conn:
            versions = am.alembic_versions(conn)
            tables = {r[0] for r in conn.exec_driver_sql(
                "select table_name from information_schema.tables where table_schema = current_schema()")}
            columns = {r[0] for r in conn.exec_driver_sql(
                "select column_name from information_schema.columns where table_name = 'am_old' "
                "and table_schema = current_schema()")}
            rows = conn.exec_driver_sql("select count(*) from am_old").scalar()
        engine.dispose()
        return versions, tables, columns, rows

    def run_am(self, body=STEP, **kwargs):
        script = scripts(Path(self.tmp.name) / f"alembic{len(list(Path(self.tmp.name).iterdir()))}", body)
        return am.run(self.out, revision=REV, parent=PARENT, backup=lambda: FRESH,
                      engine_factory=self.engine, script=script, **kwargs)

    def test_dry_run_writes_nothing(self):
        summary = self.run_am()
        self.assertEqual(summary["status"], "DRY_RUN_OK")
        self.assertEqual(summary["written"], 0)
        self.assertEqual(summary["row_counts"]["am_old"], {"rows": 3, "label": "MEASURED"})
        self.assertEqual(summary["new_tables"], ["am_new"])
        self.assertEqual(summary["backup"], FRESH)
        self.assertEqual(self.writable_opened, 0)
        self.assertEqual(self.state(), ((PARENT,), {"am_old", "alembic_version"}, {"id"}, 3))
        json.dumps(summary, default=common.json_default)

    def test_apply_then_already_applied(self):
        sha = self.run_am()["sql_plan_sha256"]
        summary = self.run_am(apply=True, expected_sha256=sha)
        self.assertEqual(summary["status"], "APPLIED")
        self.assertEqual(summary["alembic_version_after"], [REV])
        self.assertEqual(self.state(), ((REV,), {"am_old", "am_new", "alembic_version"}, {"id", "grade"}, 4))
        receipt = json.loads((self.out / "migration-receipt.json").read_text())
        self.assertEqual((receipt["revision"], receipt["parent"], receipt["sql_plan_sha256"]), (REV, PARENT, sha))
        self.assertEqual(receipt["alembic_version_after"], [REV])
        with self.assertRaisesRegex(common.Refused, "already applied"):
            self.run_am(apply=True, expected_sha256=sha)
        self.assertEqual(self.writable_opened, 1)

    def test_failure_rolls_back_everything(self):
        sha = self.run_am(FAILING)["sql_plan_sha256"]
        with self.assertRaises(Exception) as caught:
            self.run_am(FAILING, apply=True, expected_sha256=sha)
        self.assertNotIsInstance(caught.exception, AssertionError)
        self.assertEqual(self.state(), ((PARENT,), {"am_old", "alembic_version"}, {"id"}, 3))
        self.assertFalse((self.out / "migration-receipt.json").exists())

    def test_live_revision_not_parent_refuses_before_any_write(self):
        import sqlalchemy as sa

        admin = sa.create_engine(self.url, poolclass=sa.pool.NullPool)
        with admin.begin() as conn:
            conn.exec_driver_sql(f"update {self.SCHEMA}.alembic_version set version_num = '0000000000aa'")
        admin.dispose()
        with self.assertRaisesRegex(common.Refused, "not parent"):
            self.run_am()
        self.assertEqual(self.writable_opened, 0)

    def test_lock_timeout_bounds_the_wait(self):
        import sqlalchemy as sa

        sha = self.run_am()["sql_plan_sha256"]
        blocker = sa.create_engine(self.url, poolclass=sa.pool.NullPool)
        with blocker.connect() as conn, mock.patch.object(am, "LOCK_TIMEOUT_MS", 200):
            conn.exec_driver_sql(f"lock table {self.SCHEMA}.am_old in access share mode")
            with self.assertRaisesRegex(Exception, "lock timeout"):
                self.run_am(apply=True, expected_sha256=sha)
            conn.rollback()
        blocker.dispose()
        self.assertEqual(self.state(), ((PARENT,), {"am_old", "alembic_version"}, {"id"}, 3))


if __name__ == "__main__":
    unittest.main()
