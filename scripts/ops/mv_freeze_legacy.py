"""market-value-freeze-legacy: freeze the membership pre-ledger Market Value days were published with.

Owner plan A (2026-10-28). Points published before the membership ledger carry only the v1 digest
of the prints (current-corrected-card-print-release-v1:...). The plan is
app.services.market_value_membership.legacy_freeze_plan (read-only, verified staging connection):
each such revision is rebuilt from today's catalogue restricted to prints created by its last
publication, and planned only when the rebuild hashes to exactly the stored digest and reproduces
every stored scope and count. The apply re-plans while holding the market value writer's job-lock
row and writes only the approved plan. No source request; no point, snapshot or catalogue row changes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ops import common


def plan_sha(p):
    return hashlib.sha256(json.dumps(p, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def check_apply(expected_sha256, sha):
    if not (isinstance(expected_sha256, str) and len(expected_sha256) == 64
            and all(c in "0123456789abcdef" for c in expected_sha256)):
        raise common.Refused("apply needs expected_sha256: the plan SHA-256 from a dry run")
    if expected_sha256 != sha:
        raise common.Refused("the plan differs from the dry run's (expected_sha256); dry run again")


def default_preview():
    from sqlalchemy.orm import Session
    from ops import db as ops_db
    from app.services.market_value_membership import MembershipError, legacy_freeze_plan

    with Session(ops_db.engine()) as session:
        try:
            result = legacy_freeze_plan(session)
        except MembershipError as exc:
            raise common.Refused(f"market-value-freeze-legacy: {exc}") from None
        finally:
            session.rollback()
    return result


def run(out_dir, *, apply=False, expected_sha256="", preview=None, write=None):
    p, problems, facts = (preview or default_preview)()
    sha = plan_sha(p) if p else None
    summary = {"apply": bool(apply), "plan": p, "problems": problems,
               "stored_revisions": facts.get("stored_revisions"), "unfrozen": facts.get("unfrozen"),
               "rebuilds": facts.get("rebuilds", [])[:5], "plan_sha256": sha,
               "database_writes_planned": sum(e["prints"] + e["coded_releases"] + 1
                                              for e in (p or {}).get("memberships", [])),
               "source_requests": 0}
    common.write_json(Path(out_dir) / "market-value-freeze-legacy.json", {**summary, "facts": facts})
    if problems:
        summary["ok"] = False
        if apply:
            raise common.Refused("nothing to freeze: " + "; ".join(problems))
        return summary
    if not apply:
        summary["ok"] = True
        return summary
    check_apply(expected_sha256, sha)
    frozen = (write or _write_plan)(p)
    summary.update(ok=True, frozen=frozen,
                   next_step="the next market-index-snapshot run (20:00 UTC) publishes the waiting days")
    return summary


def _write_plan(p):
    """apply_legacy_freeze in one transaction after the staging fingerprint check on the write
    target. The market value writer's job-lock row is held FOR UPDATE NOWAIT for the whole
    transaction (refused while a publication or recovery holds it, and none can start until this
    commits), as the publisher guards the snapshot producer."""
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError, OperationalError
    from sqlalchemy.orm import Session
    from ops import apply_migration, db as ops_db
    from app.market_value_writer import LOCK_NAME
    from app.models.job_lock import JobLock
    from app.services.market_value_membership import MembershipError, apply_legacy_freeze

    engine, guard = apply_migration.staging_engine(writable=True)
    try:
        raw = engine.raw_connection()
        try:
            raw.driver_connection.read_only = True
            ops_db.verify(raw.driver_connection, guard)
        finally:
            raw.close()
        with Session(engine) as session:
            try:
                status = session.scalar(
                    select(JobLock.status).where(JobLock.lock_name == LOCK_NAME)
                    .with_for_update(nowait=True))
                if status is None:
                    raise MembershipError("the market value writer lock row is missing; cannot guard the freeze")
                if status == "active":
                    raise MembershipError("a market value publication or recovery is running")
                frozen = apply_legacy_freeze(session, p)
                session.commit()
            except (MembershipError, OperationalError, IntegrityError) as exc:
                session.rollback()
                raise common.Refused(f"market-value-freeze-legacy refused: {exc}") from None
    finally:
        engine.dispose()
    return frozen
