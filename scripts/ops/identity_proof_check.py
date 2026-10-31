"""identity-proof-check: why each registered physical artwork review does or does not resolve.

Owner 2026-10-31 ("go"). The 13 Claude reviews merged in #242 never resolved: resolve() swallows
every refusal (stale or unproven evidence keeps the listing ambiguous), so nothing says which check
refused. This runs the same resolver over exactly the registry's candidates on the verified
read-only staging session and records, per review, the resolver status before the proof, whether the
proof resolved, and the validator's own refusal message. It writes nothing and makes no source
request: validate() reads stored rows only, and the session is rolled back.
"""
from __future__ import annotations

from pathlib import Path

from ops import common

OUTPUT = "identity-proof-check.json"


def check(session, proofs=None):
    """Rows per registered review (read-only). `proofs` defaults to the committed registry."""
    from app.services import physical_artwork_proof as pap
    from app.services.source_mapping_proposals import ProposalFilters, analyse_source_mapping_proposals

    proofs = pap.registry() if proofs is None else proofs
    ids = sorted({p["source_candidate_id"] for p in proofs if isinstance(p.get("source_candidate_id"), int)})
    seen = {}
    original_validate, original_registry = pap.validate, pap.registry

    def recording_validate(db, plan, siblings, proof):
        entry = seen.setdefault(plan.source_candidate_id, {"pre_proof_status": plan.resolution_status})
        try:
            digest = original_validate(db, plan, siblings, proof)
        except Exception as exc:  # the refusal resolve() would swallow, named
            entry["refusal"] = f"{type(exc).__name__}: {exc}"[:300]
            raise
        entry["validated"] = True
        return digest

    import app.env as app_env
    original_env = app_env.get_app_env
    # resolve() runs only on staging; this session is the verified staging database.
    app_env.get_app_env = lambda: "staging"
    pap.validate, pap.registry = recording_validate, (lambda: proofs)
    try:
        analysis = analyse_source_mapping_proposals(
            session, ProposalFilters(source="yuyutei", candidate_ids=tuple(ids)),
            ignore_existing_mappings=True, build_report=False)
    finally:
        pap.validate, pap.registry, app_env.get_app_env = original_validate, original_registry, original_env
        session.rollback()
    outcomes = {o.candidate_id: o for o in analysis.outcomes if o.source_name == "yuyutei"}
    rows = []
    for proof in proofs:
        cid = proof.get("source_candidate_id")
        outcome, entry = outcomes.get(cid), seen.get(cid, {})
        plan = outcome.proposal if outcome else None
        final = plan.resolution_status if plan else None
        reasons = list(plan.resolution_reasons) if plan else []
        if entry.get("validated"):
            verdict = "resolved"
        elif "refusal" in entry:
            verdict = "refused"
        elif outcome is None:
            verdict = "candidate_not_analysed"
        elif final != "ambiguous":
            verdict = f"not_ambiguous_now:{final}"
        else:
            verdict = "never_reached_validator"
        rows.append({"source_candidate_id": cid, "selected_card_print_id": proof.get("selected_card_print_id"),
                     "work_id": proof.get("work_id"), "verdict": verdict,
                     "pre_proof_status": entry.get("pre_proof_status"), "final_status": final,
                     "refusal": entry.get("refusal"), "resolution_reasons": reasons[-3:]})
    return rows


def run(out_dir):
    from collections import Counter

    from sqlalchemy.orm import Session

    from ops import db as ops_db

    with Session(ops_db.engine(statement_timeout_ms=300000)) as session:
        rows = check(session)
    summary = {"reviews": len(rows), "verdicts": dict(Counter(r["verdict"] for r in rows)),
               "refusals": dict(Counter(r["refusal"][:120] for r in rows if r["refusal"])),
               "rows": rows, "source_requests": 0, "database_writes": 0}
    common.write_json(Path(out_dir) / OUTPUT, summary)
    return summary
