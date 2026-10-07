"""Execute the generated rollback against the real claim/fairness dispatcher."""

from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace

from sqlalchemy import select

from app.models import (
    FreshnessWork,
    RawSnapshot,
    SnkrdunkCandidate,
    SourceCardMapping,
    SourceDispatchBudget,
)
from app.services.freshness_queue import claim_due, plan_refresh, LANE_CYCLE
from app.services.freshness_integration import CaptureResult
from test_discovery_fences_postgres import database, counts, T0
from test_discovery_runtime import NEIGHBOUR

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import prepare_snkr_discovery_rollback as recovery


def test_checked_rollback_preserves_evidence_and_does_not_strand_raw(
    database, monkeypatch
):
    engine, factory, source_id = database
    with factory() as session:
        mapping = session.scalar(select(SourceCardMapping))
        mapping_id = mapping.id
        refresh = plan_refresh(
            session, mapping.id, {"raw"}, high_interest=False, clock=lambda: T0
        )
        refresh_id = refresh.id
        session.scalar(select(SourceDispatchBudget)).claim_sequence = LANE_CYCLE.index(
            "discovery"
        )
        session.add(
            RawSnapshot(
                source_id=source_id,
                source_url=NEIGHBOUR,
                fetched_at=T0,
                http_status=200,
                content_hash="a" * 64,
                raw_content="immutable retained fixture",
            )
        )
        session.add(
            SnkrdunkCandidate(
                source_url=NEIGHBOUR,
                title="Preserved decision",
                match_status="rejected",
                price_jpy=9999,
            )
        )
        session.commit()
        # The old refresh-only dispatcher cannot advance past the unsupported lane.
        assert (
            claim_due(
                session,
                source_id,
                "unsupported-rollback",
                limit=1,
                lease=__import__("datetime").timedelta(seconds=240),
                clock=lambda: T0,
                supported_kinds={"refresh"},
            )
            == []
        )
        session.rollback()
    baseline = subprocess.check_output(
        ["git", "show", recovery.BASE + ":" + recovery.PATH],
        cwd=recovery.ROOT,
        text=True,
    )
    module = ModuleType("checked_discovery_rollback_fixture")
    exec(
        compile(recovery.rollback_source(baseline), "<checked rollback>", "exec"),
        module.__dict__,
    )
    monkeypatch.setattr(module.settings, "SNKRDUNK_REQUEST_DELAY_MS", 0)
    seen = []

    def raw_runner(session, mapping_id, *, freshness):
        seen.append(mapping_id)
        freshness.result = CaptureResult(
            "identity_refusal", failure="offline RAW runner fixture"
        )
        return SimpleNamespace(classification=None)

    results = module.run_due(session_factory=factory, runner=raw_runner)
    assert len(results) == 2 and seen == [mapping_id]
    assert counts(factory) == {
        "SnkrdunkCandidate": 1,
        "RawSnapshot": 1,
        "SourceCardMapping": 1,
        "PriceObservation": 0,
        "FreshnessPriceState": 1,
    }
    with factory() as session:
        scope = session.scalar(
            select(FreshnessWork).where(FreshnessWork.kind == "discovery")
        )
        assert scope.state == "blocked" and scope.attempt_count == 1
        assert scope.last_failure == "published_discovery_disabled_by_rollback"
        assert session.get(FreshnessWork, refresh_id).state == "blocked"
        budget = session.scalar(select(SourceDispatchBudget))
        assert budget.reserved_requests == budget.used_requests == 0
        assert (
            session.scalar(select(RawSnapshot)).raw_content
            == "immutable retained fixture"
        )
        candidate = session.scalar(select(SnkrdunkCandidate))
        assert candidate.match_status == "rejected" and candidate.price_jpy == 9999
        assert session.get(SourceCardMapping, mapping_id).manual_verified
