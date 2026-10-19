"""Apply one allowlisted Alembic migration to staging (ops-write runbook `apply-migration`).

Agents never run `alembic upgrade` against staging and nobody runs it by hand: a schema step is
this runbook, dispatched as a dry run, reviewed by the owner, then applied with the owner's
click in the `staging-ops` Environment (docs/agent/OPS_RUNBOOKS.md).

1. Inputs: ``revision`` and ``parent``. Only the pairs in ALLOWED are accepted, and this checkout
   must carry exactly that migration as its single head on top of ``parent``.
2. Before any write: the newest Railway backup of the staging Postgres volume must be younger
   than 24 h (scripts/staging_backup_age.py) and the live alembic_version must be ``parent``.
   Already applied, any other live revision, no backup or a stale one: refused.
3. Dry run (default): writes nothing. The summary carries the migration's SQL plan (offline
   Alembic output, the SHA-256 the apply must quote), the lock budget, the tables each statement
   locks and their row counts, and the backup it checked.
4. Apply (``--apply --expected-sha256``): rebuilds the plan and refuses unless its SHA-256 equals
   the dry run's, re-checks backup and live revision, then runs only that revision in one
   transaction with lock_timeout and statement_timeout set, and records the new revision read
   back from alembic_version in migration-receipt.json. Any error rolls the whole step back,
   alembic_version included. Requests to sources: none.
"""
from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

from ops import common

# revision -> the only parent it may be applied on. Adding a pair is a reviewed code change.
ALLOWED = {"7a52e9b48e8a": "3b7d9c1a5e20"}
MAX_BACKUP_HOURS = 24
LOCK_TIMEOUT_MS = 5000
STATEMENT_TIMEOUT_MS = 120000
# Above this pg_class.reltuples a table gets the estimate, not count(*) (labelled ESTIMATE).
EXACT_COUNT_LIMIT = 1_000_000
ALEMBIC_INI = common.ROOT / "services/api/alembic.ini"
RAILWAY_BACKUPS_SETTING = ("Railway dashboard > staging project > Postgres service > the postgres-volume "
                           "volume > Backups: set a backup schedule (Daily), or press Create backup for one now")

_LOCKS = (  # (pattern, lock taken, is a new table)
    (re.compile(r"^\s*CREATE TABLE (?:IF NOT EXISTS )?(\w+)", re.I | re.M), "new table", True),
    (re.compile(r"^\s*ALTER TABLE (?:ONLY )?(\w+) ADD COLUMN", re.I | re.M), "ACCESS EXCLUSIVE", False),
    (re.compile(r"^\s*ALTER TABLE (?:ONLY )?(\w+) ADD CONSTRAINT .* NOT VALID", re.I | re.M), "ACCESS EXCLUSIVE", False),
    (re.compile(r"^\s*ALTER TABLE (?:ONLY )?(\w+) VALIDATE CONSTRAINT", re.I | re.M), "SHARE UPDATE EXCLUSIVE (full scan)", False),
    (re.compile(r"^\s*ALTER TABLE (?:ONLY )?(\w+) (?:DROP|ADD) CONSTRAINT", re.I | re.M), "ACCESS EXCLUSIVE", False),
    (re.compile(r"^\s*CREATE (?:UNIQUE )?INDEX \w+ ON (\w+)", re.I | re.M), "SHARE", False),
    (re.compile(r"^\s*INSERT INTO (\w+)", re.I | re.M), "ROW EXCLUSIVE", False),
    (re.compile(r"^\s*UPDATE (\w+)", re.I | re.M), "ROW EXCLUSIVE", False),
    (re.compile(r"\bREFERENCES (\w+)", re.I), "SHARE ROW EXCLUSIVE (new foreign key)", False),
)


def check_pair(revision, parent):
    if revision not in ALLOWED:
        raise common.Refused(f"revision {revision!r} is not allowlisted; allowed: {', '.join(sorted(ALLOWED))}")
    if parent != ALLOWED[revision]:
        raise common.Refused(f"{revision} applies only on parent {ALLOWED[revision]}, not {parent!r}")


def script_directory(ini=ALEMBIC_INI):
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(Config(str(ini)))


def check_checkout(script, revision, parent):
    """This checkout must carry ``revision`` on ``parent`` as its only head."""
    from alembic.util import CommandError

    try:
        found = script.get_revision(revision)
    except CommandError:
        found = None
    if found is None:
        raise common.Refused(f"migration {revision} is not in this checkout (merge its PR first)")
    if found.down_revision != parent:
        raise common.Refused(f"migration {revision} revises {found.down_revision}, not {parent}")
    heads = tuple(script.get_heads())
    if heads != (revision,):
        raise common.Refused(f"checkout heads are {', '.join(heads)}, not {revision} alone")


def sql_plan(script, revision, parent):
    """Offline SQL for parent -> revision only (no database touched), and its SHA-256."""
    from alembic.config import Config
    from alembic.runtime.environment import EnvironmentContext

    buffer = io.StringIO()
    config = Config(str(ALEMBIC_INI), output_buffer=buffer)
    with EnvironmentContext(config, script, fn=lambda rev, ctx: script._upgrade_revs(revision, parent),
                            as_sql=True, starting_rev=parent, destination_rev=revision) as env:
        env.configure(dialect_name="postgresql", literal_binds=True, transactional_ddl=True)
        with env.begin_transaction():
            env.run_migrations()
    text = buffer.getvalue()
    return text, hashlib.sha256(text.encode()).hexdigest()


def locks(sql):
    """{table: [locks]} for existing tables, and the new tables, from the SQL plan."""
    existing, new = {}, set()
    for pattern, lock, is_new in _LOCKS:
        for table in pattern.findall(sql):
            if is_new:
                new.add(table)
            elif table not in new and lock not in existing.setdefault(table, []):
                existing[table].append(lock)
    return {t: existing[t] for t in sorted(existing) if t not in new}, sorted(new)


def lock_budget(existing):
    held = sorted(t for t, held_locks in existing.items() if "ACCESS EXCLUSIVE" in held_locks)
    return {"lock_timeout_ms": LOCK_TIMEOUT_MS, "statement_timeout_ms": STATEMENT_TIMEOUT_MS,
            "one_transaction": True,
            "access_exclusive_until_commit": held,
            "note": "Every lock is held until the one commit, so a table under ACCESS EXCLUSIVE blocks its "
                    "readers and writers for the whole step, including any VALIDATE scan in it. A lock not "
                    "granted within lock_timeout, or a statement over statement_timeout, rolls everything back."}


def check_backup(newest, max_hours=MAX_BACKUP_HOURS):
    if newest is None:
        raise common.Refused("no Railway backup exists for the staging Postgres volume. Turn backups on: "
                             + RAILWAY_BACKUPS_SETTING)
    age = newest.get("age_hours")
    if not isinstance(age, (int, float)) or not 0 <= age < max_hours:
        raise common.Refused(f"newest staging Postgres backup is {age} h old (needs under {max_hours} h). "
                             + RAILWAY_BACKUPS_SETTING)
    return newest


def check_live(versions, revision, parent):
    versions = tuple(versions)
    if versions == (revision,):
        raise common.Refused(f"already applied: staging alembic_version is {revision}")
    if versions != (parent,):
        raise common.Refused(f"staging alembic_version is {', '.join(versions) or 'empty'}, not parent {parent}")


def check_apply(apply, expected_sha256, sha):
    if not apply:
        return
    if not (isinstance(expected_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", expected_sha256)):
        raise common.Refused("apply needs expected_sha256: the SQL plan SHA-256 from the dry run")
    if expected_sha256 != sha:
        raise common.Refused("the SQL plan differs from the dry run's (expected_sha256); dry run again")


def alembic_versions(conn):
    return tuple(r[0] for r in conn.exec_driver_sql("select version_num from alembic_version").fetchall())


def row_counts(conn, tables):
    """{table: {"rows": n, "label": MEASURED|ESTIMATE}} for existing tables. Read-only."""
    counts = {}
    for table in tables:
        found = conn.exec_driver_sql(
            "select c.reltuples::bigint from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = current_schema() and c.relname = %(t)s and c.relkind in ('r', 'p')",
            {"t": table}).fetchone()
        if found is None:
            raise common.Refused(f"table {table} from the SQL plan does not exist on staging")
        estimate = found[0]  # -1 when never analyzed: counted exactly
        if estimate > EXACT_COUNT_LIMIT:
            counts[table] = {"rows": int(estimate), "label": "ESTIMATE"}
        else:
            # Table names come from the reviewed migration's SQL (\w+ only), never from input.
            counts[table] = {"rows": conn.exec_driver_sql(f'select count(*) from "{table}"').scalar(),
                             "label": "MEASURED"}
    return counts


def upgrade(conn, script, revision, parent):
    """Run parent -> revision on ``conn`` inside one transaction; return alembic_version after."""
    from alembic.config import Config
    from alembic.runtime.environment import EnvironmentContext

    with conn.begin():
        conn.exec_driver_sql(f"set local lock_timeout = {LOCK_TIMEOUT_MS}")
        conn.exec_driver_sql(f"set local statement_timeout = {STATEMENT_TIMEOUT_MS}")
        # Holds the version row until commit: a second runner waits, then sees the new revision.
        live = tuple(r[0] for r in conn.exec_driver_sql("select version_num from alembic_version for update"))
        check_live(live, revision, parent)
        config = Config(str(ALEMBIC_INI))
        with EnvironmentContext(config, script, fn=lambda rev, ctx: script._upgrade_revs(revision, rev),
                                destination_rev=revision) as env:
            env.configure(connection=conn, transaction_per_migration=False)
            env.run_migrations()
        after = alembic_versions(conn)
        if after != (revision,):
            raise common.Refused(f"alembic_version after the step is {after}, not {revision}; rolled back")
    return after


def staging_engine(*, writable):
    """Pinned staging Postgres; fingerprint checked with the PARENT as the expected revision."""
    import sqlalchemy
    import psycopg
    import staging_db_read_check as guard

    from ops import db as ops_db

    proxy, variables = ops_db.resolve()
    try:
        kwargs = ops_db.connect_kwargs(proxy, variables, STATEMENT_TIMEOUT_MS)
    finally:
        variables.clear()
    if writable:
        kwargs["options"] = kwargs["options"].replace(ops_db.READ_ONLY_OPTION, "").strip()

    def connect():
        try:
            return psycopg.connect(**kwargs)
        except Exception:
            raise common.Refused("staging database connection failed") from None

    return sqlalchemy.create_engine("postgresql+psycopg://", creator=connect,
                                    poolclass=sqlalchemy.pool.NullPool), guard


def fingerprint(engine, guard, parent):
    """The read-only staging fingerprint, expecting the parent revision (not this checkout's head)."""
    raw = engine.raw_connection()
    try:
        raw.read_only = True
        checks = guard.evaluate(guard.collect_facts(raw), frozenset({parent}))
        raw.rollback()
    finally:
        raw.close()
    failed = [c.name for c in checks if not c.ok and c.name != "fingerprint D - alembic revision"]
    if failed:
        raise common.Refused("staging database fingerprint failed: " + ", ".join(failed))


def newest_backup():
    import staging_backup_age

    return staging_backup_age.newest_backup()


def run(out_dir, *, apply=False, revision="", parent="", expected_sha256="",
        backup=newest_backup, engine_factory=staging_engine, script=None):
    out = Path(out_dir)
    check_pair(revision, parent)
    script = script or script_directory()
    check_checkout(script, revision, parent)
    sql, sha = sql_plan(script, revision, parent)
    (out / "migration-plan.sql").write_text(sql)
    check_apply(apply, expected_sha256, sha)
    existing, new_tables = locks(sql)
    newest = check_backup(backup())

    engine, guard = engine_factory(writable=False)
    try:
        if guard is not None:
            fingerprint(engine, guard, parent)
        with engine.connect() as conn:
            check_live(alembic_versions(conn), revision, parent)
            counts = row_counts(conn, existing)
            conn.rollback()
    finally:
        engine.dispose()

    summary = {"mode": "apply" if apply else "dry-run", "status": "DRY_RUN_OK", "revision": revision,
               "parent": parent, "sql_plan_sha256": sha, "sql_statements": sql.count(";"),
               "backup": newest, "live_revision": parent, "existing_tables_locked": existing,
               "new_tables": new_tables, "row_counts": counts, "lock_budget": lock_budget(existing),
               "source_requests": 0, "written": 0}
    if not apply:
        return summary

    engine, _ = engine_factory(writable=True)
    try:
        with engine.connect() as conn:
            after = upgrade(conn, script, revision, parent)
    finally:
        engine.dispose()
    receipt = {"revision": revision, "parent": parent, "alembic_version_after": list(after),
               "sql_plan_sha256": sha, "backup": newest, "applied_at": common.now_utc().isoformat()}
    common.write_json(out / "migration-receipt.json", receipt)
    summary.update(status="APPLIED", written=1, alembic_version_after=list(after),
                   applied_at=receipt["applied_at"])
    return summary
