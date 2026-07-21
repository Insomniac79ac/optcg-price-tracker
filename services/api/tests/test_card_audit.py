import pytest

from app.models import Card, PriceObservation, Source, SourceCardMapping
from app.models.snkrdunk_candidate import SnkrdunkCandidate
from app.services.card_audit import run_card_audit


def make_card(db_session, **overrides) -> Card:
    fields = dict(
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        name_jp="モンキー・D・ルフィ",
        set_code="OP01",
        rarity="L",
        variant="leader",
        language="en",
    )
    fields.update(overrides)
    card = Card(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


@pytest.fixture()
def yuyutei(db_session) -> Source:
    source = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def test_clean_catalog_has_no_issues(db_session, yuyutei):
    card = make_card(db_session)
    db_session.add(
        SourceCardMapping(
            card_id=card.id,
            source_id=yuyutei.id,
            source_card_id=card.card_code,
            source_url="https://yuyu-tei.jp/product/op01-001",
        )
    )
    db_session.commit()
    # A recent price observation, or app.services.price_source_health's
    # source_price_missing check (see _check_source_price_health) correctly
    # flags this mapping as never-refreshed - "clean" now also means "has a
    # recent price", not just "has a mapping".
    db_session.add(
        PriceObservation(card_id=card.id, source_id=yuyutei.id, price_type="sell", price_jpy=1000)
    )
    db_session.commit()

    report = run_card_audit(db_session)

    assert report.total_cards == 1
    assert report.issues == []


def test_detects_conflicting_names_for_same_card_code(db_session):
    card_a = make_card(db_session, name_en="Monkey D. Luffy", rarity="L", variant="leader")
    card_b = make_card(db_session, name_en="Monkey.D.Luffy", rarity="SR", variant="alt_art")

    report = run_card_audit(db_session)

    issues = [i for i in report.issues if i.issue_type == "duplicate_card_code_conflicting_names"]
    assert len(issues) == 1
    issue = issues[0]
    assert issue.severity == "critical"
    assert issue.card_code == "OP01-001"
    assert set(issue.card_ids) == {card_a.id, card_b.id}


def test_detects_inconsistent_language_values(db_session):
    consistent = make_card(db_session, card_code="OP01-002", rarity="R", variant=None, language="jp")
    inconsistent = make_card(
        db_session, card_code="OP01-003", rarity="R", variant=None, language="Japanese"
    )

    report = run_card_audit(db_session)

    issues = [i for i in report.issues if i.issue_type == "inconsistent_language_values"]
    assert len(issues) == 1
    issue = issues[0]
    assert issue.severity == "warning"
    assert issue.card_ids == [inconsistent.id]
    assert consistent.id not in issue.card_ids
    assert issue.details == {"raw_value": "Japanese", "canonical_value": "jp"}


def test_detects_duplicate_source_urls(db_session, yuyutei):
    card_a = make_card(db_session, card_code="OP01-004", rarity="R", variant="a")
    card_b = make_card(db_session, card_code="OP01-005", rarity="R", variant="b")

    db_session.add_all(
        [
            SourceCardMapping(
                card_id=card_a.id,
                source_id=yuyutei.id,
                source_card_id="OP01-004",
                source_url="https://yuyu-tei.jp/product/1",
            ),
            SourceCardMapping(
                card_id=card_b.id,
                source_id=yuyutei.id,
                source_card_id="OP01-005",
                source_url="https://yuyu-tei.jp/Product/1",
            ),
        ]
    )
    db_session.commit()

    report = run_card_audit(db_session)

    issues = [i for i in report.issues if i.issue_type == "duplicate_source_url"]
    assert len(issues) == 1
    issue = issues[0]
    assert issue.severity == "critical"
    assert set(issue.card_ids) == {card_a.id, card_b.id}


def test_detects_source_card_code_mismatch(db_session, yuyutei):
    card = make_card(db_session, card_code="OP01-006", rarity="R", variant=None)
    db_session.add(
        SourceCardMapping(
            card_id=card.id,
            source_id=yuyutei.id,
            source_card_id="OP01-999",
            source_url="https://yuyu-tei.jp/product/2",
        )
    )
    db_session.commit()

    report = run_card_audit(db_session)

    issues = [i for i in report.issues if i.issue_type == "source_card_code_mismatch"]
    assert len(issues) == 1
    issue = issues[0]
    assert issue.severity == "critical"
    assert issue.card_ids == [card.id]
    assert issue.card_code == "OP01-006"


def test_detects_cards_without_mappings(db_session):
    card = make_card(db_session, card_code="OP01-007", rarity="R", variant=None)

    report = run_card_audit(db_session)

    issues = [i for i in report.issues if i.issue_type == "cards_without_source_mappings"]
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].card_ids == [card.id]


def test_detects_cards_with_prices_but_no_active_mapping(db_session, yuyutei):
    card = make_card(db_session, card_code="OP01-008", rarity="R", variant=None)
    db_session.add(
        PriceObservation(
            card_id=card.id,
            source_id=yuyutei.id,
            price_type="listing",
            price_jpy=1000,
        )
    )
    db_session.commit()

    report = run_card_audit(db_session)

    issues = [
        i for i in report.issues if i.issue_type == "cards_with_prices_but_no_active_mapping"
    ]
    assert len(issues) == 1
    assert issues[0].severity == "critical"
    assert issues[0].card_ids == [card.id]


def test_detects_low_confidence_mapping_legacy_fraction_scale(db_session, yuyutei):
    card = make_card(db_session, card_code="OP01-010", rarity="R", variant=None)
    db_session.add(
        SourceCardMapping(
            card_id=card.id,
            source_id=yuyutei.id,
            source_card_id=card.card_code,
            source_url="https://yuyu-tei.jp/product/low-conf",
            match_confidence=0.4,
        )
    )
    db_session.commit()

    report = run_card_audit(db_session)

    issues = [i for i in report.issues if i.issue_type == "low_match_confidence_mapping"]
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].card_ids == [card.id]
    assert issues[0].details["match_confidence_score"] == 40.0


def test_detects_low_confidence_mapping_raw_score_scale(db_session, yuyutei):
    card = make_card(db_session, card_code="OP01-011", rarity="R", variant=None)
    db_session.add(
        SourceCardMapping(
            card_id=card.id,
            source_id=yuyutei.id,
            source_card_id=card.card_code,
            source_url="https://yuyu-tei.jp/product/low-conf-raw",
            match_confidence=45,
        )
    )
    db_session.commit()

    report = run_card_audit(db_session)

    issues = [i for i in report.issues if i.issue_type == "low_match_confidence_mapping"]
    assert len(issues) == 1
    assert issues[0].details["match_confidence_score"] == 45.0


def test_high_confidence_mapping_is_not_flagged(db_session, yuyutei):
    card = make_card(db_session, card_code="OP01-012", rarity="R", variant=None)
    db_session.add(
        SourceCardMapping(
            card_id=card.id,
            source_id=yuyutei.id,
            source_card_id=card.card_code,
            source_url="https://yuyu-tei.jp/product/high-conf",
            match_confidence=0.95,
        )
    )
    db_session.commit()

    report = run_card_audit(db_session)

    issues = [i for i in report.issues if i.issue_type == "low_match_confidence_mapping"]
    assert issues == []


def test_detects_candidate_variant_mismatch(db_session):
    card = make_card(db_session, card_code="OP05-119", rarity="SEC", variant="alt_art")
    db_session.add(
        SnkrdunkCandidate(
            source_url="https://snkrdunk.com/trading-cards/variant-mismatch",
            title="OP05-119 Kaido",
            match_status="matched",
            matched_card_id=card.id,
            match_explanation_json={
                "positive": ["exact card_code match"],
                "negative": ["variant mismatch"],
                "caps_applied": ["variant_mismatch_cap_75"],
            },
        )
    )
    db_session.commit()

    report = run_card_audit(db_session)

    issues = [i for i in report.issues if i.issue_type == "candidate_variant_mismatch"]
    assert len(issues) == 1


def test_includes_critical_mapping_quality_issues_and_summary(db_session, yuyutei):
    card = make_card(db_session, card_code="OP01-013", rarity="R", variant=None)
    for i in range(2):
        db_session.add(
            SourceCardMapping(
                card_id=card.id,
                source_id=yuyutei.id,
                source_card_id="OP01-013",
                source_url=f"https://yuyu-tei.jp/product/dup{'' if i == 0 else ' '}",
            )
        )
    db_session.commit()

    report = run_card_audit(db_session)

    critical_issues = [i for i in report.issues if i.issue_type == "critical_mapping_quality"]
    assert len(critical_issues) == 2
    assert report.mapping_quality is not None
    assert report.mapping_quality["critical_count"] == 2
    assert report.mapping_quality["duplicate_source_url_count"] == 2

    payload = report.to_dict()
    assert payload["summary"]["mapping_quality"]["critical_count"] == 2


def test_card_audit_endpoint_returns_report(client, db_session, yuyutei):
    card = make_card(db_session, card_code="OP01-009", rarity="R", variant=None)

    response = client.get("/admin/card-audit")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total_cards"] == 1
    assert body["summary"]["total_issues"] >= 1
    issue_types = {issue["issue_type"] for issue in body["issues"]}
    assert "cards_without_source_mappings" in issue_types
    assert card.id in next(
        issue["card_ids"]
        for issue in body["issues"]
        if issue["issue_type"] == "cards_without_source_mappings"
    )


def test_card_audit_detects_duplicate_card_identity(db_session):
    card_a = make_card(db_session, card_code="OP01-010", rarity="L")
    card_b = make_card(db_session, card_code="OP01-010", rarity="SR")

    report = run_card_audit(db_session)

    issues = [i for i in report.issues if i.issue_type == "duplicate_card_identity"]
    assert len(issues) == 1
    assert set(issues[0].card_ids) == {card_a.id, card_b.id}


def test_card_audit_detects_inactive_card_without_merge_target(db_session):
    card = make_card(db_session, card_code="OP01-011", rarity="L", is_active=False)

    report = run_card_audit(db_session)

    issues = [i for i in report.issues if i.issue_type == "inactive_card_without_merge_target"]
    assert len(issues) == 1
    assert card.id in issues[0].card_ids


def test_card_audit_detects_active_card_merged_into_another(db_session):
    card = make_card(db_session, card_code="OP01-012", rarity="L", merged_into_card_id=999)

    report = run_card_audit(db_session)

    issues = [i for i in report.issues if i.issue_type == "active_card_merged_into_another_card"]
    assert len(issues) == 1
    assert card.id in issues[0].card_ids


def test_card_audit_detects_merged_card_with_active_mapping(db_session, yuyutei):
    from app.services.card_identity_merge import MergeOptions, execute_card_merge

    card_a = make_card(db_session, card_code="OP01-013", rarity="L")
    card_b = make_card(db_session, card_code="OP01-013", rarity="SR")
    execute_card_merge(db_session, card_b.id, card_a.id, MergeOptions(dry_run=False))

    # Simulate a mapping that was left active/pointing at the merged card,
    # bypassing the normal merge reassignment path.
    db_session.add(
        SourceCardMapping(
            card_id=card_b.id,
            source_id=yuyutei.id,
            source_card_id=card_b.card_code,
            source_url="https://yuyu-tei.jp/stale",
            is_active=True,
        )
    )
    db_session.commit()

    report = run_card_audit(db_session)

    issues = [
        i for i in report.issues if i.issue_type == "merged_card_still_has_active_source_mapping"
    ]
    assert len(issues) == 1
    assert issues[0].card_ids == [card_b.id]
