"""yuyu-source-probe: authorize ONE Yuyu-Tei probe after a source denial pause (owner-gated).

Owner decision 2026-10-26 (perfectionist). One challenge page from Yuyu-Tei (2026-10-25 16:27Z)
paused every Yuyu-Tei shard (source_dispatch_budgets.pause_reason = source_denial, no timer).
Clearing the pause blindly could send up to nine shards into the same challenge. Instead:

1. Dry run (read-only, verified staging connection): app.services.source_recovery.
   preview_yuyu_probe reports the Yuyu-Tei budget (must be paused for source_denial), the latest
   denial and the pause chain it belongs to (the refresh or discovery denial that paused the
   source; probes that met a challenge stay in the same chain), the probes already used for this
   pause (all closed, at most 3; after a challenged probe the next waits 6 hours), and the probe
   mapping: the approved, eligible Yuyu-Tei mapping whose refresh last captured cleanly.
   plan_sha256 covers the whole plan (source, chain, denial, probe number, mapping, print,
   product identity, request bound).
2. apply=true with that SHA: re-runs the same preview, refuses unless the SHA matches, then
   calls plan_yuyu_probe in one transaction, which re-runs the preview under the budget row lock
   and refuses unless the plan is identical. It records one authorized, unattempted validation
   scope; it makes no request and reserves nothing.
3. The next scheduled Yuyu shard turn serves it (yuyutei_collector.recovery): one metered product
   capture from the collectors' own network, identity validated, no price written. Only a
   completed, identity-verified HTTP 200 capture clears the pause; a challenge keeps it paused.
   Every probe is closed after its one attempt; another needs a new dry run and approval.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ops import common


def plan_sha(p):
    from app.services.source_recovery import YUYU_PROBE_PLAN_KEYS

    return hashlib.sha256(json.dumps({k: p[k] for k in YUYU_PROBE_PLAN_KEYS}, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def check_apply(expected_sha256, sha):
    if not (isinstance(expected_sha256, str) and len(expected_sha256) == 64
            and all(c in "0123456789abcdef" for c in expected_sha256)):
        raise common.Refused("apply needs expected_sha256: the plan SHA-256 from a dry run")
    if expected_sha256 != sha:
        raise common.Refused("the plan differs from the dry run's (expected_sha256); dry run again")


def _summary(facts, p, problems, sha):
    d, m = facts.get("denial") or {}, facts.get("mapping") or {}
    return {"paused_for": (facts.get("budget") or {}).get("pause_reason"),
            "denial": d or None, "pause_chain_root": facts.get("root_denial_attempt_id"),
            "probe_mapping": {k: m.get(k) for k in ("mapping_id", "card_print_id", "source_url", "last_success")},
            "earlier_probes": facts.get("probes") or [], "probe_number": (p or {}).get("probe_number"),
            "request_bound": (p or {}).get("request_bound"),
            "problems": problems, "plan_sha256": sha, "source_requests": 0}


def _source_id(session):
    from sqlalchemy import select
    from app.models import Source

    source_id = session.scalar(select(Source.id).where(Source.name == "yuyutei"))
    if source_id is None:
        raise common.Refused("no Yuyu-Tei source found")
    return source_id


def default_preview():
    """preview_yuyu_probe on a verified read-only staging session."""
    from sqlalchemy.orm import Session
    from ops import db as ops_db
    from app.services.source_recovery import preview_yuyu_probe

    with Session(ops_db.engine()) as session:
        result = preview_yuyu_probe(session, _source_id(session))
        session.rollback()
    return result


def run(out_dir, *, apply=False, expected_sha256="", preview=None, write=None):
    p, problems, facts = (preview or default_preview)()
    sha = plan_sha(p) if p else None
    summary = _summary(facts, p, problems, sha)
    summary["apply"] = bool(apply)
    common.write_json(Path(out_dir) / "yuyu-source-probe.json", {**summary, "plan": p, "facts": facts})
    if problems:
        summary["ok"] = False
        if apply:
            raise common.Refused("no probe can be planned: " + "; ".join(problems))
        return summary
    if not apply:
        summary["ok"] = True
        return summary
    check_apply(expected_sha256, sha)
    work_id = (write or _write_plan)(p)
    summary.update(ok=True, probe_work_id=work_id, written=1,
                   next_step="the next scheduled Yuyu-Tei shard turn serves the probe (at most 30 minutes)")
    return summary


def _write_plan(p):
    """plan_yuyu_probe in one transaction: it re-runs the preview under the budget lock and
    writes only when the plan equals the approved one."""
    from sqlalchemy.orm import Session
    from ops import apply_migration
    from app.services.source_recovery import plan_yuyu_probe

    engine, _guard = apply_migration.staging_engine(writable=True)
    try:
        with Session(engine) as session:
            try:
                work = plan_yuyu_probe(session, p["source_id"], p)
                work_id = work.id
                session.commit()
            except ValueError as exc:
                session.rollback()
                raise common.Refused(f"plan_yuyu_probe refused: {exc}") from None
    finally:
        engine.dispose()
    return work_id
