"""Coverage for the read-only import planner (app.services.print_import_planner).

Hermetic: in-memory sqlite, entries constructed here, digests supplied by a
dict. Nothing reaches the network or a real database.

The load-bearing assertions are the refusals - that `_pN` never becomes a
treatment, that prose never becomes a product identity, and that a changed
asset never becomes a second print. Those are the mistakes the exact-print
identity exists to prevent, so they are tested directly rather than implied.
"""

import pytest
from sqlalchemy import event

from app.models import CanonicalCard, CardPrint, ReleaseProduct
from app.services.official_cardlist import OfficialCardEntry, OfficialSeries
from app.services.print_import_planner import (
    CREATE_CANONICAL_CARD,
    CREATE_CARD_PRINT,
    CREATE_RELEASE_PRODUCT,
    FLAG_ASSET_CHANGED,
    FLAG_CANONICAL_CARD_CONFLICT,
    FLAG_MALFORMED_ASSET,
    FLAG_RARITY_DIFFERS_BY_PRINTING,
    FLAG_UNCODED_PRODUCT,
    OUTCOME_CONFLICT,
    OUTCOME_CREATE,
    OUTCOME_NEEDS_REVIEW,
    OUTCOME_NO_CHANGE,
    PrintImportPlanner,
    original_set_code,
    plan_entries,
)

CARDLIST = "https://www.onepiece-cardgame.com/images/cardlist/card"
OP01_SERIES = OfficialSeries(
    series_id="550101",
    display_name="ブースターパック ROMANCE DAWN【OP-01】",
    official_code="OP-01",
)
SERIES_INDEX = (OP01_SERIES,)

BASE_DIGEST = "a" * 64
P1_DIGEST = "b" * 64


def entry(
    entry_id="OP01-001",
    card_code="OP01-001",
    image=f"{CARDLIST}/OP01-001.png?260821",
    products=("ROMANCE DAWN【OP-01】",),
    name="ロロノア・ゾロ",
    rarity="L",
    category="LEADER",
) -> OfficialCardEntry:
    return OfficialCardEntry(
        entry_id=entry_id,
        card_code=card_code,
        rarity=rarity,
        category=category,
        card_name=name,
        image_url=image,
        product_names=products,
    )


@pytest.fixture()
def op01(db_session) -> ReleaseProduct:
    product = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code="OP-01",
        display_name="ブースターパック ROMANCE DAWN【OP-01】",
        first_seen_name="ブースターパック ROMANCE DAWN【OP-01】",
        source_series_id="550101",
        source_url="https://www.onepiece-cardgame.com/products/boosters/op01.php",
        verification_status="verified",
    )
    db_session.add(product)
    db_session.commit()
    return product


@pytest.fixture()
def zoro(db_session) -> CanonicalCard:
    card = CanonicalCard(
        card_code="OP01-001",
        name_jp="ロロノア・ゾロ",
        name_en="Roronoa Zoro",
        original_set_code="OP-01",
        rarity="L",
        card_type="Leader",
    )
    db_session.add(card)
    db_session.commit()
    return card


def make_print(db_session, card, product, variant, **overrides) -> CardPrint:
    fields = dict(
        canonical_card_id=card.id,
        language="jp",
        treatment="parallel",
        release_product_code="OP-01",
        release_product_id=product.id,
        artwork_key=BASE_DIGEST,
        official_artwork_variant=variant,
        image_url=f"{CARDLIST}/OP01-001.png",
        verification_status="verified",
        is_active=True,
    )
    fields.update(overrides)
    row = CardPrint(**fields)
    db_session.add(row)
    db_session.commit()
    return row


def plan_one(session, the_entry, *, digests=None, sibling_count=1):
    planner = PrintImportPlanner(
        session, digest_provider=(digests or {}).get if digests is not None else None
    )
    return planner.plan_entry(
        the_entry, series_index=SERIES_INDEX, sibling_count=sibling_count
    )


# --- 1. existing exact print -> no_change -----------------------------------


def test_an_existing_exact_print_resolves_to_no_change(db_session, op01, zoro):
    make_print(db_session, zoro, op01, "base")
    planned = plan_one(
        db_session, entry(), digests={f"{CARDLIST}/OP01-001.png?260821": BASE_DIGEST}
    )
    assert planned.outcome == OUTCOME_NO_CHANGE
    assert planned.action == "no_change"
    assert planned.creations == ()
    assert planned.existing_card_print_id is not None


def test_the_match_is_the_four_identity_columns_not_treatment_or_artwork_key(
    db_session, op01, zoro
):
    """A print differing only in treatment and artwork_key is still the match."""
    make_print(db_session, zoro, op01, "base", treatment="normal", artwork_key="c" * 64)
    planned = plan_one(db_session, entry())
    assert planned.outcome == OUTCOME_NO_CHANGE
    assert planned.treatment == "normal"


def test_a_print_with_a_different_variant_is_not_a_match(db_session, op01, zoro):
    """Same card, same product, different official artwork = a different print."""
    make_print(db_session, zoro, op01, "p1")
    planned = plan_one(
        db_session, entry(), digests={f"{CARDLIST}/OP01-001.png?260821": BASE_DIGEST}
    )
    assert planned.outcome == OUTCOME_CREATE
    assert planned.existing_card_print_id is None


def test_a_print_of_another_card_with_the_same_code_shape_is_not_a_match(
    db_session, op01, zoro
):
    """Card code alone never matches when siblings exist."""
    make_print(db_session, zoro, op01, "p2")
    planned = plan_one(
        db_session,
        entry(),
        digests={f"{CARDLIST}/OP01-001.png?260821": BASE_DIGEST},
        sibling_count=2,
    )
    assert planned.existing_card_print_id is None
    assert planned.outcome == OUTCOME_CREATE


# --- 2/3. missing canonical card, missing base print ------------------------


def test_a_missing_canonical_card_and_print_are_both_planned(db_session, op01):
    planned = plan_one(
        db_session,
        entry(card_code="OP01-999", entry_id="OP01-999", image=f"{CARDLIST}/OP01-999.png"),
        digests={f"{CARDLIST}/OP01-999.png": BASE_DIGEST},
    )
    assert planned.outcome == OUTCOME_CREATE
    assert set(planned.creations) == {CREATE_CANONICAL_CARD, CREATE_CARD_PRINT}
    assert planned.action == "create_multiple"
    assert planned.proposed_canonical_card is not None
    assert planned.proposed_canonical_card.card_code == "OP01-999"
    assert planned.proposed_canonical_card.original_set_code == "OP-01"
    assert planned.proposed_canonical_card.card_type == "Leader"


def test_an_existing_card_missing_its_base_print_plans_only_the_print(
    db_session, op01, zoro
):
    make_print(db_session, zoro, op01, "p2")
    planned = plan_one(
        db_session,
        entry(),
        digests={f"{CARDLIST}/OP01-001.png?260821": BASE_DIGEST},
    )
    assert planned.outcome == OUTCOME_CREATE
    assert planned.creations == (CREATE_CARD_PRINT,)
    assert planned.action == "create_card_print"
    assert planned.existing_canonical_card_id == zoro.id


def test_a_proposed_canonical_card_carries_only_fields_bandai_supplies(db_session, op01):
    planned = plan_one(
        db_session,
        entry(card_code="OP01-998", entry_id="OP01-998", image=f"{CARDLIST}/OP01-998.png"),
        digests={f"{CARDLIST}/OP01-998.png": BASE_DIGEST},
    )
    proposed = planned.proposed_canonical_card
    assert proposed.name_jp == "ロロノア・ゾロ"
    assert proposed.rarity == "L"
    # Nothing Bandai does not publish is invented: no name_en, cost, power.
    assert not hasattr(proposed, "name_en")
    assert not hasattr(proposed, "cost")


# --- 4/5. several artworks, and the treatment refusal -----------------------


def test_multiple_pn_assets_plan_as_distinct_variants(db_session, op01, zoro):
    entries = [
        entry(),
        entry(entry_id="OP01-001_p1", image=f"{CARDLIST}/OP01-001_p1.png"),
        entry(entry_id="OP01-001_p2", image=f"{CARDLIST}/OP01-001_p2.png"),
    ]
    plan = plan_entries(
        db_session,
        entries,
        series_index=SERIES_INDEX,
        digest_provider={
            f"{CARDLIST}/OP01-001.png?260821": BASE_DIGEST,
            f"{CARDLIST}/OP01-001_p1.png": P1_DIGEST,
            f"{CARDLIST}/OP01-001_p2.png": "d" * 64,
        }.get,
        classify_mappings=False,
    )
    variants = [p.official_artwork_variant for p in plan.prints]
    assert variants == ["base", "p1", "p2"]
    # Three separate prints, never collapsed into one.
    assert all(p.outcome == OUTCOME_CREATE for p in plan.prints)
    assert len({tuple(p.creations) for p in plan.prints}) == 1


def test_pn_never_determines_treatment(db_session, op01, zoro):
    """The whole point: a suffix is an artwork address, not a finish."""
    for suffix, variant in (("", "base"), ("_p1", "p1"), ("_p2", "p2"), ("_p3", "p3")):
        planned = plan_one(
            db_session,
            entry(
                entry_id=f"OP01-001{suffix}",
                image=f"{CARDLIST}/OP01-001{suffix}.png",
            ),
            digests={f"{CARDLIST}/OP01-001{suffix}.png": BASE_DIGEST},
        )
        assert planned.official_artwork_variant == variant
        assert planned.treatment is None, f"{suffix} invented a treatment"
        assert "parallel" not in str(planned.to_dict()).lower().replace("parallel_", "")


def test_a_new_print_may_be_verified_with_treatment_null(db_session, op01, zoro):
    planned = plan_one(
        db_session,
        entry(entry_id="OP01-001_p1", image=f"{CARDLIST}/OP01-001_p1.png"),
        digests={f"{CARDLIST}/OP01-001_p1.png": P1_DIGEST},
    )
    assert planned.treatment is None
    assert planned.verification_status == "verified"


def test_an_existing_treatment_is_preserved_never_recomputed(db_session, op01, zoro):
    make_print(db_session, zoro, op01, "p1", treatment="manga")
    planned = plan_one(
        db_session,
        entry(entry_id="OP01-001_p1", image=f"{CARDLIST}/OP01-001_p1.png"),
        digests={f"{CARDLIST}/OP01-001_p1.png": BASE_DIGEST},
    )
    assert planned.treatment == "manga"


# --- 6/7. product identity ---------------------------------------------------


def test_an_existing_product_is_reused_by_catalogue_and_official_code(
    db_session, op01, zoro
):
    planned = plan_one(
        db_session, entry(), digests={f"{CARDLIST}/OP01-001.png?260821": BASE_DIGEST}
    )
    assert planned.existing_release_product_id == op01.id
    assert CREATE_RELEASE_PRODUCT not in planned.creations


def test_a_product_in_another_catalogue_is_not_reused(db_session, zoro):
    """A code is unique only within its catalogue."""
    other = ReleaseProduct(
        source_catalogue="bandai_en",
        official_code="OP-01",
        display_name="Romance Dawn [OP-01]",
        first_seen_name="Romance Dawn [OP-01]",
        source_series_id="569101",
        source_url="https://en.onepiece-cardgame.com/",
    )
    db_session.add(other)
    db_session.commit()
    planned = plan_one(
        db_session, entry(), digests={f"{CARDLIST}/OP01-001.png?260821": BASE_DIGEST}
    )
    assert planned.existing_release_product_id is None
    assert CREATE_RELEASE_PRODUCT in planned.creations


def test_an_uncoded_product_never_hashes_prose_into_identity(db_session, zoro):
    """No code means a surrogate id decided at write time - never a name key."""
    planned = plan_one(
        db_session,
        entry(products=("週刊少年ジャンプ応募者全員サービス",)),
        digests={f"{CARDLIST}/OP01-001.png?260821": BASE_DIGEST},
    )
    assert FLAG_UNCODED_PRODUCT in planned.flags
    assert planned.outcome == OUTCOME_NEEDS_REVIEW
    proposed = planned.proposed_release_product
    assert proposed is not None
    assert proposed.official_code is None
    # The verbatim name is kept as evidence, and is not any kind of key.
    assert proposed.first_seen_name == "週刊少年ジャンプ応募者全員サービス"
    assert not hasattr(proposed, "id")
    assert not hasattr(proposed, "normalized_name")


def test_a_similar_uncoded_name_is_never_silently_merged(db_session, zoro):
    established = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code=None,
        display_name="週刊少年ジャンプ応募者全員サービス 2023",
        first_seen_name="週刊少年ジャンプ応募者全員サービス 2023",
        source_series_id="569901",
        source_url="https://www.onepiece-cardgame.com/cardlist/?series=569901",
    )
    db_session.add(established)
    db_session.commit()
    planned = plan_one(
        db_session,
        entry(products=("週刊少年ジャンプ応募者全員サービス",)),
        digests={f"{CARDLIST}/OP01-001.png?260821": BASE_DIGEST},
    )
    # A near-identical name is a *different* product until a human says so.
    assert planned.existing_release_product_id is None
    assert CREATE_RELEASE_PRODUCT in planned.creations


def test_an_established_uncoded_product_is_reused_on_an_exact_name(db_session, zoro):
    established = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code=None,
        display_name="週刊少年ジャンプ応募者全員サービス",
        first_seen_name="週刊少年ジャンプ応募者全員サービス",
        source_series_id="569901",
        source_url="https://www.onepiece-cardgame.com/cardlist/?series=569901",
    )
    db_session.add(established)
    db_session.commit()
    planned = plan_one(
        db_session,
        entry(products=("週刊少年ジャンプ応募者全員サービス",)),
        digests={f"{CARDLIST}/OP01-001.png?260821": BASE_DIGEST},
    )
    assert planned.existing_release_product_id == established.id
    assert CREATE_RELEASE_PRODUCT not in planned.creations


def test_an_entry_naming_two_products_is_never_resolved_to_one(db_session, op01, zoro):
    planned = plan_one(
        db_session,
        entry(products=("ROMANCE DAWN【OP-01】", "Premium Collection")),
        digests={f"{CARDLIST}/OP01-001.png?260821": BASE_DIGEST},
    )
    assert planned.outcome == OUTCOME_NEEDS_REVIEW


# --- 8. conflicting existing card -------------------------------------------


def test_a_conflicting_canonical_card_is_flagged_never_overwritten(db_session, op01):
    card = CanonicalCard(
        card_code="OP01-001",
        name_jp="まちがった名前",
        original_set_code="OP-01",
        rarity="SR",
        card_type="Character",
    )
    db_session.add(card)
    db_session.commit()
    planned = plan_one(
        db_session, entry(), digests={f"{CARDLIST}/OP01-001.png?260821": BASE_DIGEST}
    )
    assert planned.outcome == OUTCOME_CONFLICT
    assert planned.verification_status == "needs_review"
    assert FLAG_CANONICAL_CARD_CONFLICT in planned.flags
    assert planned.proposed_canonical_card is None  # nothing is rewritten
    # Unchanged in the database.
    db_session.refresh(card)
    assert card.name_jp == "まちがった名前"


def test_a_missing_atlas_value_is_not_a_conflict(db_session, op01):
    """A NULL in Atlas is missing information, not a contradiction."""
    card = CanonicalCard(
        card_code="OP01-001",
        name_jp=None,
        name_en="Roronoa Zoro",
        original_set_code="OP-01",
        rarity="L",
        card_type="Leader",
    )
    db_session.add(card)
    db_session.commit()
    planned = plan_one(
        db_session, entry(), digests={f"{CARDLIST}/OP01-001.png?260821": BASE_DIGEST}
    )
    assert planned.outcome != OUTCOME_CONFLICT


# --- 9. changed asset --------------------------------------------------------


def test_a_changed_asset_flags_rather_than_duplicating(db_session, op01, zoro):
    existing = make_print(db_session, zoro, op01, "base", artwork_key=BASE_DIGEST)
    planned = plan_one(
        db_session,
        entry(),
        digests={f"{CARDLIST}/OP01-001.png?260821": "f" * 64},
    )
    assert FLAG_ASSET_CHANGED in planned.flags
    assert planned.existing_card_print_id == existing.id
    # The one thing that must never happen.
    assert CREATE_CARD_PRINT not in planned.creations
    assert planned.outcome == OUTCOME_NEEDS_REVIEW


def test_a_changed_address_with_the_same_bytes_is_not_a_change(db_session, op01, zoro):
    """Bandai's cache buster moves without the artwork moving."""
    make_print(db_session, zoro, op01, "base", artwork_key=BASE_DIGEST)
    planned = plan_one(
        db_session,
        entry(image=f"{CARDLIST}/OP01-001.png?999999"),
        digests={f"{CARDLIST}/OP01-001.png?999999": BASE_DIGEST},
    )
    assert FLAG_ASSET_CHANGED not in planned.flags
    assert planned.outcome == OUTCOME_NO_CHANGE


# --- 10. malformed assets ----------------------------------------------------


@pytest.mark.parametrize(
    "image",
    [
        f"{CARDLIST}/OP01-002.png",  # the asset names another card
        f"{CARDLIST}/OP01-001.jpg",  # not a Card List asset
        f"{CARDLIST}/OP01-001_P1.png",  # not an address Bandai serves
        f"{CARDLIST}/OP01-001_p01.png",  # second spelling of p1
        None,
    ],
)
def test_a_malformed_asset_is_needs_review_never_guessed(db_session, op01, zoro, image):
    planned = plan_one(db_session, entry(image=image), digests={})
    assert planned.official_artwork_variant is None
    assert FLAG_MALFORMED_ASSET in planned.flags
    assert planned.outcome == OUTCOME_NEEDS_REVIEW
    assert planned.verification_status == "needs_review"


def test_an_entry_id_disagreeing_with_the_asset_is_needs_review(db_session, op01, zoro):
    planned = plan_one(
        db_session,
        entry(entry_id="OP01-001_p9", image=f"{CARDLIST}/OP01-001_p1.png"),
        digests={f"{CARDLIST}/OP01-001_p1.png": P1_DIGEST},
    )
    assert planned.outcome == OUTCOME_NEEDS_REVIEW


def test_without_a_digest_a_new_print_is_not_verified(db_session, op01, zoro):
    """Coverage is never bought by lowering the evidence standard."""
    planned = plan_one(db_session, entry(), digests=None)
    assert planned.official_artwork_sha256 is None
    assert planned.outcome == OUTCOME_NEEDS_REVIEW
    assert planned.verification_status == "needs_review"


# --- 11. no writes -----------------------------------------------------------


def test_planning_writes_nothing(db_session, op01, zoro):
    """Any flush at all fails this test, whatever it would have contained."""
    make_print(db_session, zoro, op01, "p2")
    flushes: list[object] = []

    @event.listens_for(db_session, "before_flush")
    def _record(session, flush_context, instances):  # pragma: no cover - must not fire
        flushes.append(instances)

    before = {
        "cards": db_session.query(CanonicalCard).count(),
        "prints": db_session.query(CardPrint).count(),
        "products": db_session.query(ReleaseProduct).count(),
    }
    plan = plan_entries(
        db_session,
        [entry(), entry(entry_id="OP01-001_p2", image=f"{CARDLIST}/OP01-001_p2.png")],
        series_index=SERIES_INDEX,
        digest_provider={}.get,
        classify_mappings=True,
    )
    assert plan.prints
    assert flushes == []
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    assert before == {
        "cards": db_session.query(CanonicalCard).count(),
        "prints": db_session.query(CardPrint).count(),
        "products": db_session.query(ReleaseProduct).count(),
    }


def test_the_planner_module_contains_no_write_verbs():
    """A structural guard: no INSERT/UPDATE/DELETE can hide in the planner."""
    from pathlib import Path

    import app.services.print_import_planner as module

    source = Path(module.__file__).read_text()
    # Strip the docstrings/comments that legitimately discuss writing.
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    for forbidden in ("session.add", "session.commit", "session.flush", "session.delete"):
        assert forbidden not in code, forbidden
    assert "self._session.add" not in code


def test_the_cli_exposes_no_write_flag():
    from app.plan_canonical_print_import import build_parser

    options = {
        option
        for action in build_parser()._actions
        for option in action.option_strings
    }
    for forbidden in ("--apply", "--write", "--persist", "--commit", "--force"):
        assert forbidden not in options, forbidden


# --- helpers ------------------------------------------------------------------


def test_original_set_code_is_read_out_of_the_card_code():
    assert original_set_code("OP01-001") == "OP-01"
    assert original_set_code("OP04-118") == "OP-04"
    assert original_set_code("EB01-012") == "EB-01"
    assert original_set_code("") is None
    assert original_set_code("NOTACODE") is None


def test_a_rarity_difference_in_the_cards_own_set_is_a_conflict(db_session, op01):
    """Same set, different rarity: the catalogue and Atlas really do disagree."""
    card = CanonicalCard(
        card_code="OP01-001",
        name_jp="ロロノア・ゾロ",
        original_set_code="OP-01",
        rarity="SR",
        card_type="Leader",
    )
    db_session.add(card)
    db_session.commit()
    planned = plan_one(
        db_session, entry(rarity="L"), digests={f"{CARDLIST}/OP01-001.png?260821": BASE_DIGEST}
    )
    assert planned.outcome == OUTCOME_CONFLICT
    assert FLAG_CANONICAL_CARD_CONFLICT in planned.flags


def test_a_reprints_rarity_is_a_note_not_a_canonical_conflict(db_session, zoro):
    """Bandai lists rarity per printing.

    OP02-013 is 'SR' in OP-02 and 'SPカード' in its OP-08 reprint (observed
    2026-08-22). Reporting that as a canonical-card conflict would invite
    someone to 'correct' a canonical card that is already right.
    """
    later_set = OfficialSeries(
        series_id="550108",
        display_name="ブースターパック 二つの伝説【OP-08】",
        official_code="OP-08",
    )
    planner = PrintImportPlanner(
        db_session,
        digest_provider={f"{CARDLIST}/OP01-001_p3.png": BASE_DIGEST}.get,
    )
    planned = planner.plan_entry(
        entry(
            entry_id="OP01-001_p3",
            image=f"{CARDLIST}/OP01-001_p3.png",
            products=("ブースターパック 二つの伝説【OP-08】",),
            rarity="SPカード",
        ),
        series_index=(OP01_SERIES, later_set),
    )
    assert planned.outcome != OUTCOME_CONFLICT
    assert FLAG_CANONICAL_CARD_CONFLICT not in planned.flags
    assert FLAG_RARITY_DIFFERS_BY_PRINTING in planned.flags
    # And the canonical card is still not rewritten by anything here.
    assert planned.proposed_canonical_card is None


# --- 12. lineage-less source mappings, read-only ------------------------------


def _mapping(db_session, card_code, source_name, **overrides):
    from app.models import Card, Source, SourceCardMapping

    card = db_session.query(Card).filter_by(card_code=card_code).one_or_none()
    if card is None:
        card = Card(
            card_code=card_code,
            name_en=card_code,
            set_code="OP-01",
            rarity="L",
            language="jp",
        )
        db_session.add(card)
        db_session.flush()
    source = db_session.query(Source).filter_by(name=source_name).one_or_none()
    if source is None:
        source = Source(name=source_name, base_url=f"https://{source_name}.example")
        db_session.add(source)
        db_session.flush()
    fields = dict(
        card_id=card.id,
        source_id=source.id,
        card_print_id=None,
        source_card_id=f"{source_name}-{card_code}",
        source_url=f"https://{source_name}.example/{card_code}",
        review_status="approved",
        is_active=True,
    )
    fields.update(overrides)
    row = SourceCardMapping(**fields)
    db_session.add(row)
    db_session.commit()
    return row


def _plan_for(db_session, entries):
    return plan_entries(
        db_session,
        entries,
        series_index=SERIES_INDEX,
        digest_provider={}.get,
        classify_mappings=True,
    )


def test_a_mapping_naming_the_official_artwork_is_an_exact_candidate(db_session, op01, zoro):
    _mapping(
        db_session,
        "OP01-001",
        "yuyutei",
        match_explanation_json={"matched_bandai_artwork": "OP01-001_p2"},
    )
    plan = _plan_for(
        db_session,
        [entry(), entry(entry_id="OP01-001_p2", image=f"{CARDLIST}/OP01-001_p2.png")],
    )
    assert [m.classification for m in plan.mappings] == ["exact_candidate"]


def test_a_mapping_for_a_card_with_one_artwork_is_probable(db_session, op01, zoro):
    _mapping(db_session, "OP01-001", "yuyutei")
    plan = _plan_for(db_session, [entry()])
    assert [m.classification for m in plan.mappings] == ["probable"]


def test_a_mapping_for_a_card_with_siblings_and_no_evidence_is_ambiguous(
    db_session, op01, zoro
):
    _mapping(db_session, "OP01-001", "yuyutei")
    plan = _plan_for(
        db_session,
        [entry(), entry(entry_id="OP01-001_p2", image=f"{CARDLIST}/OP01-001_p2.png")],
    )
    assert [m.classification for m in plan.mappings] == ["ambiguous"]


def test_a_rejected_mapping_is_never_promoted_by_a_lucky_code_match(
    db_session, op01, zoro
):
    _mapping(db_session, "OP01-001", "snkrdunk", review_status="rejected")
    plan = _plan_for(db_session, [entry()])
    assert [m.classification for m in plan.mappings] == ["ambiguous"]


def test_a_mapping_for_another_card_is_unrelated(db_session, op01, zoro):
    _mapping(db_session, "OP09-055", "yuyutei")
    plan = _plan_for(db_session, [entry()])
    assert [m.classification for m in plan.mappings] == ["unrelated"]


def test_a_mapping_with_lineage_is_not_classified_at_all(db_session, op01, zoro):
    """Only lineage-less rows are the planner's business."""
    existing = make_print(db_session, zoro, op01, "base")
    _mapping(db_session, "OP01-001", "yuyutei", card_print_id=existing.id)
    plan = _plan_for(db_session, [entry()])
    assert plan.mappings == []


def test_classifying_mappings_never_attaches_or_edits_one(db_session, op01, zoro):
    row = _mapping(db_session, "OP01-001", "yuyutei")
    before = (row.card_print_id, row.review_status, row.is_active, row.match_explanation_json)
    _plan_for(db_session, [entry()])
    db_session.refresh(row)
    assert (row.card_print_id, row.review_status, row.is_active, row.match_explanation_json) == before
    assert row.card_print_id is None
