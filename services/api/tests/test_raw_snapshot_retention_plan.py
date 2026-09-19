from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import event, func, select
from sqlalchemy.orm import sessionmaker

from app import raw_snapshot_retention_plan as plan_cli
from app.models import (
    PriceObservation,
    RawSnapshot,
    Source,
    SourceCollectionAttempt,
    YuyuteiCandidate,
)
from app.services.raw_snapshot_retention_plan import (
    POLICY_VERSION,
    build_raw_snapshot_retention_plan,
    canonicalize_snapshot_url,
)

NOW = datetime(2026, 9, 16, 12, tzinfo=timezone.utc)
BODY_MARKER = "SECRET_HTML_BODY_NEVER_EMIT"


def _snapshot(
    source: Source,
    *,
    url: str,
    age_days: int,
    status: int = 200,
    parser_version: str | None = "yuyutei-collector-v3",
    minute: int = 0,
) -> RawSnapshot:
    return RawSnapshot(
        source_id=source.id,
        source_url=url,
        fetched_at=NOW - timedelta(days=age_days, minutes=-minute),
        http_status=status,
        content_hash=f"hash-{source.id}-{age_days}-{status}-{minute}-{url}",
        raw_content=f"{BODY_MARKER}:{url}:{minute}",
        parser_version=parser_version,
    )


def _category_ids(payload: dict, category: str) -> set[int]:
    return set(payload["categories"][category]["sample_ids"])


def _add_failure_attempt(
    db_session,
    snapshot: RawSnapshot,
    *,
    ordinal: int,
    source_denied: bool = False,
) -> SourceCollectionAttempt:
    attempt = SourceCollectionAttempt(
        batch_run_id=f"batch-{ordinal}",
        source_id=snapshot.source_id,
        source_card_mapping_id=ordinal,
        selection_ordinal=ordinal,
        selected_at=NOW,
        started_at=NOW,
        finished_at=NOW,
        status="validation_failed",
        failure_stage="homepage" if source_denied else "validation",
        failure_reason="static_403" if source_denied else "validation_failed",
        source_denied=source_denied,
        raw_snapshot_id=snapshot.id,
    )
    db_session.add(attempt)
    return attempt


def test_canonicalization_uses_only_existing_exact_source_rules():
    jp = canonicalize_snapshot_url("snkrdunk", "https://snkrdunk.com/apparels/4242")
    en = canonicalize_snapshot_url(
        "snkrdunk",
        "https://snkrdunk.com/en/trading-cards/4242?query_id=known-mirror",
    )
    history = canonicalize_snapshot_url(
        "snkrdunk", "https://snkrdunk.com/apparels/4242/sales-histories"
    )
    ambiguous_history = canonicalize_snapshot_url(
        "snkrdunk",
        "https://snkrdunk.com/apparels/4242/sales-histories?unknown=1",
    )
    unknown_a = canonicalize_snapshot_url(
        "snkrdunk", "https://snkrdunk.com/unknown/4242?a=1"
    )
    unknown_b = canonicalize_snapshot_url(
        "snkrdunk", "https://snkrdunk.com/unknown/4242?a=2"
    )
    yuyu_a = canonicalize_snapshot_url(
        "yuyutei", "https://yuyu-tei.jp/sell/opc/card/op01/10152"
    )
    yuyu_b = canonicalize_snapshot_url(
        "yuyutei",
        "https://yuyu-tei.jp/sell/opc/card/op01/10152?from=listing",
    )

    assert jp.key == en.key == "snkrdunk:product:4242"
    assert jp.equivalence_proven is True
    assert history.key == "snkrdunk:sales_history:4242"
    assert history.key != jp.key
    assert ambiguous_history.role is None
    assert ambiguous_history.equivalence_proven is False
    assert unknown_a.key != unknown_b.key
    assert yuyu_a.key == yuyu_b.key == "yuyutei:product:op01:10152"


def test_planner_classifies_required_protection_reasons_conservatively(db_session):
    yuyu = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
    snkr = Source(name="snkrdunk", base_url="https://snkrdunk.com")
    db_session.add_all([yuyu, snkr])
    db_session.flush()

    recent = _snapshot(
        yuyu,
        url="https://yuyu-tei.jp/sell/opc/card/op01/1001",
        age_days=1,
    )
    observation_linked = _snapshot(
        yuyu,
        url="https://yuyu-tei.jp/sell/opc/card/op01/1002",
        age_days=100,
    )
    unreferenced_403 = _snapshot(
        yuyu,
        url="https://yuyu-tei.jp/",
        age_days=1,
        status=403,
    )
    attempt_failure = _snapshot(
        yuyu,
        url="https://yuyu-tei.jp/sell/opc/card/op01/1003",
        age_days=100,
    )
    sales_history = _snapshot(
        snkr,
        url="https://snkrdunk.com/apparels/9001/sales-histories",
        age_days=100,
        parser_version="snkrdunk-collector-v2",
    )
    unreferenced_error = _snapshot(
        snkr,
        url="https://snkrdunk.com/sitemap/missing",
        age_days=100,
        status=404,
        parser_version="snkrdunk-discovery-v1",
    )
    discovery = _snapshot(
        snkr,
        url="https://snkrdunk.com/sitemap/cards.xml",
        age_days=100,
        parser_version="snkrdunk-discovery-v1",
    )
    insufficient = _snapshot(
        yuyu,
        url="https://yuyu-tei.jp/unknown/page",
        age_days=100,
        parser_version=None,
    )
    daily_first = _snapshot(
        yuyu,
        url="https://yuyu-tei.jp/sell/opc/card/op02/2001",
        age_days=100,
        minute=1,
    )
    daily_later = _snapshot(
        yuyu,
        url="https://yuyu-tei.jp/sell/opc/card/op02/2001",
        age_days=100,
        minute=2,
    )
    multi_reason = _snapshot(
        yuyu,
        url="https://yuyu-tei.jp/",
        age_days=1,
        status=403,
        minute=3,
    )
    identity_evidence = _snapshot(
        yuyu,
        url="https://yuyu-tei.jp/sell/opc/card/op03/3001",
        age_days=100,
    )
    db_session.add_all(
        [
            recent,
            observation_linked,
            unreferenced_403,
            attempt_failure,
            sales_history,
            unreferenced_error,
            discovery,
            insufficient,
            daily_first,
            daily_later,
            multi_reason,
            identity_evidence,
        ]
    )
    db_session.flush()

    db_session.add(
        PriceObservation(
            source_id=yuyu.id,
            price_type="sell",
            price_jpy=1000,
            raw_snapshot_id=observation_linked.id,
        )
    )
    _add_failure_attempt(db_session, attempt_failure, ordinal=1)
    _add_failure_attempt(db_session, multi_reason, ordinal=2, source_denied=True)
    db_session.add(
        YuyuteiCandidate(
            set_slug="op03",
            product_id="3001",
            source_url=identity_evidence.source_url,
            match_status="unmatched",
        )
    )
    db_session.commit()

    payload = build_raw_snapshot_retention_plan(
        db_session, sample_limit=50, now=NOW
    ).to_dict()

    assert recent.id in _category_ids(payload, "recent_full_retention")
    assert observation_linked.id in _category_ids(payload, "observation_linked")
    assert observation_linked.id in _category_ids(payload, "audit_or_lineage_hold")
    assert unreferenced_403.id in _category_ids(payload, "attempt_failure_evidence")
    assert unreferenced_403.id in _category_ids(payload, "source_denied_evidence")
    assert attempt_failure.id in _category_ids(payload, "attempt_failure_evidence")
    assert sales_history.id in _category_ids(payload, "snkrdunk_sales_history_evidence")
    assert unreferenced_error.id in _category_ids(payload, "attempt_failure_evidence")
    assert discovery.id in _category_ids(payload, "discovery_evidence")
    assert insufficient.id in _category_ids(payload, "unclassified_protected")
    assert daily_first.id in _category_ids(payload, "daily_representative_required")
    assert daily_later.id in _category_ids(payload, "potentially_eligible")
    assert identity_evidence.id in _category_ids(
        payload, "candidate_or_identity_evidence"
    )

    multi_ids = {
        snapshot_id
        for overlap in payload["overlaps"].values()
        for snapshot_id in overlap["sample_ids"]
    }
    assert multi_reason.id in multi_ids
    assert payload["categories"]["potentially_eligible"]["count"] == 1


def test_old_success_with_insufficient_metadata_is_never_eligible(db_session):
    source = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
    db_session.add(source)
    db_session.flush()
    snapshot = _snapshot(
        source,
        url="https://yuyu-tei.jp/unclassified",
        age_days=500,
        parser_version=None,
    )
    db_session.add(snapshot)
    db_session.commit()

    payload = build_raw_snapshot_retention_plan(
        db_session, sample_limit=10, now=NOW
    ).to_dict()

    assert snapshot.id in _category_ids(payload, "unclassified_protected")
    assert snapshot.id not in _category_ids(payload, "potentially_eligible")
    assert payload["classification_gaps"]["unknown_role_count"] == 1


def test_planner_is_select_only_zero_write_and_never_calls_pruning(
    db_session, monkeypatch
):
    source = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
    db_session.add(source)
    db_session.flush()
    snapshot = _snapshot(
        source,
        url="https://yuyu-tei.jp/sell/opc/card/op01/7777",
        age_days=1,
    )
    db_session.add(snapshot)
    db_session.commit()

    import app.services.data_retention as deletion_module

    def forbidden_prune(*_args, **_kwargs):
        raise AssertionError("planner called deletion path")

    monkeypatch.setattr(deletion_module, "prune_tables", forbidden_prune)
    before = db_session.scalar(select(func.count()).select_from(RawSnapshot))
    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lstrip().upper())

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture_statement)
    try:
        payload = build_raw_snapshot_retention_plan(
            db_session, sample_limit=10, now=NOW
        ).to_dict()
    finally:
        event.remove(bind, "before_cursor_execute", capture_statement)

    after = db_session.scalar(select(func.count()).select_from(RawSnapshot))
    assert before == after == 1
    assert statements
    assert all(statement.startswith("SELECT") for statement in statements)
    assert not db_session.new
    assert not db_session.dirty
    assert not db_session.deleted
    assert BODY_MARKER not in json.dumps(payload)


def test_report_shape_samples_and_body_redaction(db_session):
    source = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
    db_session.add(source)
    db_session.flush()
    db_session.add_all(
        [
            _snapshot(
                source,
                url=f"https://yuyu-tei.jp/sell/opc/card/op01/{number}",
                age_days=1,
                minute=number,
            )
            for number in (1, 2, 3)
        ]
    )
    db_session.commit()

    payload = build_raw_snapshot_retention_plan(
        db_session, sample_limit=1, now=NOW
    ).to_dict()

    assert payload["policy_version"] == POLICY_VERSION
    assert payload["read_only"] is True
    assert payload["policy"]["execution_enabled"] is False
    assert payload["totals"]["snapshot_count"] == 3
    assert payload["totals"]["estimated_stored_bytes"] > 0
    assert payload["by_source"]["yuyutei"]["count"] == 3
    assert set(payload["by_age_bucket"]) == {
        "<7 days",
        "7-30 days",
        "31-90 days",
        "91-180 days",
        "181-365 days",
        ">365 days",
    }
    assert all(
        len(bucket["sample_ids"]) <= 1 for bucket in payload["categories"].values()
    )
    assert "missing_durable_metadata" in payload["classification_gaps"]
    assert BODY_MARKER not in json.dumps(payload)
    assert "raw_content" not in json.dumps(payload)


def test_cli_emits_structured_json_without_mutation(db_session, monkeypatch, capsys):
    source = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
    db_session.add(source)
    db_session.flush()
    db_session.add(
        _snapshot(
            source,
            url="https://yuyu-tei.jp/sell/opc/card/op01/9999",
            age_days=1,
        )
    )
    db_session.commit()

    cli_session_factory = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, autocommit=False
    )
    monkeypatch.setattr(plan_cli, "SessionLocal", cli_session_factory)

    assert plan_cli.main(["--sample-limit", "1", "--compact"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["read_only"] is True
    assert payload["policy_version"] == POLICY_VERSION
    assert payload["sample_limit"] == 1
    assert payload["totals"]["snapshot_count"] == 1
    assert BODY_MARKER not in json.dumps(payload)
