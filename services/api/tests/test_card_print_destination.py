"""GET /cards/{card_id}/print-destination: the retired /cards/{id} page's redirect target.

Collector v1 S6 (PLAN E1, B2). A legacy card names a print only when it reaches
exactly one active print through active, approved, unsuperseded mappings; any
other card falls back to its code's version chooser, and an unknown id is 404.
"""

from __future__ import annotations

from tests.test_prints import (
    make_canonical,
    make_legacy_card,
    make_mapping,
    make_print,
    make_source,
)


def _print(db, code, **kwargs):
    return make_print(db, make_canonical(db, card_code=code), artwork_key=f"art-{code}", **kwargs)


def _world(db):
    yuyu = make_source(db, "yuyutei")
    snkr = make_source(db, "snkrdunk")
    exact_print = _print(db, "OP01-001")
    exact = make_legacy_card(db, card_code="OP01-001", set_code="A")
    # Two mappings to the same print are still exactly one print.
    make_mapping(db, exact, yuyu, exact_print)
    make_mapping(db, exact, snkr, exact_print, source_card_id="s-1")
    two = make_legacy_card(db, card_code="OP01-002", set_code="B")
    make_mapping(db, two, yuyu, _print(db, "OP01-002"))
    make_mapping(db, two, snkr, _print(db, "OP02-003"), source_card_id="s-2")
    none = make_legacy_card(db, card_code="OP02-004", set_code="C")
    # Mappings that must never resolve: inactive, needs review, inactive print.
    stale = make_legacy_card(db, card_code="OP01-005", set_code="D")
    stale_print = _print(db, "OP01-005")
    make_mapping(db, stale, yuyu, stale_print, is_active=False, source_card_id="x-1")
    make_mapping(db, stale, snkr, stale_print, review_status="needs_review", source_card_id="x-2")
    make_mapping(
        db, stale, make_source(db, "other"), _print(db, "OP01-099", is_active=False), source_card_id="x-3"
    )
    db.commit()
    return exact, exact_print, two, none, stale


def test_exact_unique_card_names_its_print(client, db_session):
    exact, exact_print, *_ = _world(db_session)
    response = client.get(f"/cards/{exact.id}/print-destination")
    assert response.status_code == 200
    assert response.json() == {
        "card_id": exact.id,
        "card_code": "OP01-001",
        "card_print_id": exact_print.id,
        "resolution": "exact",
    }


def test_card_reaching_two_prints_names_none(client, db_session):
    _, _, two, *_ = _world(db_session)
    body = client.get(f"/cards/{two.id}/print-destination").json()
    assert body["card_print_id"] is None
    assert body["resolution"] == "multiple_prints"
    assert body["card_code"] == "OP01-002"


def test_unmapped_and_never_resolving_mappings_name_none(client, db_session):
    _, _, _, none, stale = _world(db_session)
    for card, code in ((none, "OP02-004"), (stale, "OP01-005")):
        body = client.get(f"/cards/{card.id}/print-destination").json()
        assert body == {"card_id": card.id, "card_code": code, "card_print_id": None, "resolution": "no_print"}


def test_unknown_card_is_404(client, db_session):
    _world(db_session)
    response = client.get("/cards/999999/print-destination")
    assert response.status_code == 404


def test_destination_matches_the_legacy_copy_rule(db_session):
    from app.accounts.migrate_legacy import resolve_legacy_cards

    exact, exact_print, two, none, stale = _world(db_session)
    reached = resolve_legacy_cards(db_session)
    assert reached[exact.id] == {exact_print.id}
    assert len(reached[two.id]) == 2
    assert none.id not in reached and stale.id not in reached
