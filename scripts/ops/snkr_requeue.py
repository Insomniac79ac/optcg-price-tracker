"""snkr-parser-requeue: reopen SNKRDUNK refresh work refused by the class-name parser bug (owner-gated).

Owner decision 2026-10-27 (perfectionist): a canary first, then the rest. The plan is
app.services.snkr_parser_requeue.preview (read-only, verified staging connection); the apply
re-runs it under row locks and writes only the approved plan. No source request.

- count=1: canary. Reopens the one refused item with the newest earlier clean capture. Wait for
  the next SNKRDUNK turn to capture it (staging-state, db-diagnostic snkrdunk-quarantine).
- count empty: rest. Needs a refused item that has since captured a price on the new code, and
  nothing refused again on it. Reopens every remaining refused item.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ops import common


def plan_sha(p):
    from app.services.snkr_parser_requeue import PLAN_KEYS

    return hashlib.sha256(json.dumps({k: p[k] for k in PLAN_KEYS}, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def check_apply(expected_sha256, sha):
    if not (isinstance(expected_sha256, str) and len(expected_sha256) == 64
            and all(c in "0123456789abcdef" for c in expected_sha256)):
        raise common.Refused("apply needs expected_sha256: the plan SHA-256 from a dry run")
    if expected_sha256 != sha:
        raise common.Refused("the plan differs from the dry run's (expected_sha256); dry run again")


def mode_for(count):
    if count is None:
        return "rest"
    if count == 1:
        return "canary"
    raise common.Refused("snkr-parser-requeue: count 1 is the canary; leave it empty for the rest")


def default_preview(mode):
    """preview on a verified read-only staging session."""
    from sqlalchemy.orm import Session
    from ops import db as ops_db
    from app.services.snkr_parser_requeue import preview

    with Session(ops_db.engine()) as session:
        result = preview(session, mode=mode)
        session.rollback()
    return result


def run(out_dir, *, apply=False, count=None, expected_sha256="", preview=None, write=None):
    mode = mode_for(count)
    p, problems, facts = (preview or default_preview)(mode)
    sha = plan_sha(p) if p else None
    summary = {"mode": mode, "apply": bool(apply), "reopen": len(p["work_ids"]) if p else 0,
               "work_ids_sample": (p["work_ids"][:10] if p else []), "problems": problems,
               "candidates": facts.get("candidates"), "ineligible": len(facts.get("ineligible") or []),
               "proven_captures": facts.get("proven_captures", [])[:10],
               "open_requeues": facts.get("open_requeues", [])[:10],
               "refused_on_new_code": len(facts.get("refused_on_new_code") or []),
               "plan_sha256": sha, "source_requests": 0}
    common.write_json(Path(out_dir) / "snkr-parser-requeue.json", {**summary, "plan": p, "facts": facts})
    if problems:
        summary["ok"] = False
        if apply:
            raise common.Refused("nothing can be reopened: " + "; ".join(problems))
        return summary
    if not apply:
        summary["ok"] = True
        return summary
    check_apply(expected_sha256, sha)
    reopened = (write or _write_plan)(p)
    summary.update(ok=True, written=len(reopened),
                   next_step="the next scheduled SNKRDUNK turn refreshes the reopened work")
    return summary


def _write_plan(p):
    """apply() in one transaction after the staging fingerprint check on the write target."""
    from sqlalchemy.orm import Session
    from ops import apply_migration, db as ops_db
    from app.services.snkr_parser_requeue import apply

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
                reopened = apply(session, p)
                session.commit()
            except ValueError as exc:
                session.rollback()
                raise common.Refused(f"snkr-parser-requeue refused: {exc}") from None
    finally:
        engine.dispose()
    return reopened
