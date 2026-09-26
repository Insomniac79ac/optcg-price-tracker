"""Read-only projection tests for the Market Value replay adapter."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import event

from app.models.canonical_card import CanonicalCard
from app.models.card_print import CardPrint
from app.models.market_index_snapshot import MarketIndexSnapshot
from app.models.release_product import ReleaseProduct
from app.services import market_value_replay


def test_replay_input_loader_selects_only_and_uses_release_fk(
    db_session, monkeypatch
) -> None:
    release = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code="OP-17",
        display_name="The World's Strongest Warriors",
        first_seen_name="The World's Strongest Warriors",
        source_series_id="series-1",
        source_url="https://example.invalid/op-17",
        verification_status="verified",
    )
    card = CanonicalCard(
        card_code="EB04-007",
        name_en="Mixed-code regression",
        card_type="CHARACTER",
    )
    db_session.add_all([release, card])
    db_session.flush()
    physical_print = CardPrint(
        canonical_card_id=card.id,
        language="jp",
        release_product_id=release.id,
        official_asset_variant="p2",
        artwork_key="a" * 64,
        verification_status="verified",
        is_active=True,
    )
    db_session.add(physical_print)
    db_session.flush()
    db_session.add(
        MarketIndexSnapshot(
            card_print_id=physical_print.id,
            calculated_at=datetime(2026, 9, 25, 20, tzinfo=timezone.utc),
            snapshot_date=date(2026, 9, 25),
            index_value_jpy=500,
            calculation_method="median",
            source_count=1,
            coverage_status="full",
            confidence="high",
            index_version=3,
            source_semantics_version=2,
            provenance={
                "source_values": [
                    {
                        "source": "yuyutei",
                        "reference_type": "retail_ask",
                        "contributes_to_index": True,
                        "value_jpy": 500,
                    }
                ]
            },
        )
    )
    db_session.commit()

    # Keep this test about archived projection. The live resolver is already
    # covered at its own boundary and is intentionally not needed here.
    monkeypatch.setattr(
        market_value_replay, "select_snapshottable_print_ids", lambda _db: []
    )
    statements: list[str] = []

    def record_statement(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    event.listen(db_session.get_bind(), "before_cursor_execute", record_statement)
    try:
        loaded = market_value_replay.load_market_value_replay_input(db_session)
    finally:
        event.remove(
            db_session.get_bind(), "before_cursor_execute", record_statement
        )

    assert statements and set(statements) == {"SELECT"}
    assert loaded.active_prints[0].release_product_id == release.id
    assert loaded.coded_releases[0].release_product_id == release.id
    assert loaded.observations_by_date[date(2026, 9, 25)][0].card_print_id == (
        physical_print.id
    )
    assert loaded.observations_by_date[date(2026, 9, 25)][0].contributors == (
        frozenset({("yuyutei", "retail_ask")})
    )
