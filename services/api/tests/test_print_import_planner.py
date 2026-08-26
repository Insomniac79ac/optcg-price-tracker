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
from sqlalchemy.exc import MultipleResultsFound

from app.models import CanonicalCard, CardPrint, ReleaseProduct
from app.services.official_cardlist import OfficialCardEntry, OfficialSeries
from app.services.print_import_planner import (
    CREATE_CANONICAL_CARD,
    CREATE_CARD_PRINT,
    CREATE_RELEASE_PRODUCT,
    FLAG_ASSET_CHANGED,
    FLAG_CANONICAL_CARD_CONFLICT,
    FLAG_MALFORMED_ASSET,
    FLAG_NAME_DIFFERS_BY_PRINTING,
    FLAG_RARITY_DIFFERS_BY_PRINTING,
    FLAG_UNCODED_PRODUCT,
    OUTCOME_CONFLICT,
    OUTCOME_CREATE,
    OUTCOME_NEEDS_REVIEW,
    OUTCOME_NO_CHANGE,
    PrintImportPlanner,
    is_promo_card_code,
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
        official_asset_variant=variant,
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
    variants = [p.official_asset_variant for p in plan.prints]
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
        assert planned.official_asset_variant == variant
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
    assert planned.official_asset_variant is None
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


# --- 10b. the r family -------------------------------------------------------
#
# Admitting rN was the point of tranche 4B-3. Three cards in the complete
# 2026-08-22 JP corpus publish both `_r1` and `_r2` inside PRB-01 - OP01-120,
# OP05-074 and OP05-119 - and under the previous p-only vocabulary both of
# each pair resolved to None, collided under the exact-print key, and landed
# in needs_review as a malformed asset. These assert that the planner now
# reads them as identity, and still reads nothing else out of them.


R1_DIGEST = "c" * 64
R2_DIGEST = "d" * 64


@pytest.mark.parametrize("variant", ["r1", "r2", "r3"])
def test_an_rn_asset_is_planned_as_identity_not_as_malformed(db_session, op01, zoro, variant):
    image = f"{CARDLIST}/OP01-001_{variant}.png?260821"
    planned = plan_one(
        db_session,
        entry(entry_id=f"OP01-001_{variant}", image=image),
        digests={image: R1_DIGEST},
    )

    assert planned.official_asset_variant == variant
    assert FLAG_MALFORMED_ASSET not in planned.flags
    assert planned.outcome == OUTCOME_CREATE
    assert planned.verification_status == "verified"


@pytest.mark.parametrize("variant", ["r1", "r2", "r3"])
def test_an_rn_asset_never_produces_a_treatment(db_session, op01, zoro, variant):
    """The whole reason the field is called *asset* and not *artwork*: rN says
    which official asset, and nothing about parallel/manga/special/rarity."""
    image = f"{CARDLIST}/OP01-001_{variant}.png"
    planned = plan_one(
        db_session, entry(image=image, entry_id=f"OP01-001_{variant}"), digests={image: R1_DIGEST}
    )

    assert planned.treatment is None
    assert planned.official_asset_variant == variant


def test_r1_and_r2_in_one_product_are_planned_as_two_distinct_prints(db_session, op01, zoro):
    """The OP01-120 / OP05-074 / OP05-119 shape. Under the p-only vocabulary
    these two collapsed into one identity; now they are simply two."""
    r1_image = f"{CARDLIST}/OP01-001_r1.png"
    r2_image = f"{CARDLIST}/OP01-001_r2.png"

    plan = plan_entries(
        db_session,
        [
            entry(entry_id="OP01-001_r1", image=r1_image),
            entry(entry_id="OP01-001_r2", image=r2_image),
        ],
        series_index=SERIES_INDEX,
        digest_provider={r1_image: R1_DIGEST, r2_image: R2_DIGEST}.get,
    )

    variants = [p.official_asset_variant for p in plan.prints]
    assert variants == ["r1", "r2"]
    # Two identities, not one - and each is a create in its own right.
    assert {p.outcome for p in plan.prints} == {OUTCOME_CREATE}
    identities = {
        (p.card_code, p.official_product_code, p.official_asset_variant) for p in plan.prints
    }
    assert len(identities) == 2


def test_an_rn_print_with_identical_bytes_to_base_is_still_its_own_identity(
    db_session, op01, zoro
):
    """152 rN assets in the JP corpus are byte-for-byte identical to a base
    asset. An equal digest is equal *evidence*, never a merged identity."""
    base_image = f"{CARDLIST}/OP01-001.png"
    r1_image = f"{CARDLIST}/OP01-001_r1.png"
    shared = BASE_DIGEST

    plan = plan_entries(
        db_session,
        [
            entry(entry_id="OP01-001", image=base_image),
            entry(entry_id="OP01-001_r1", image=r1_image),
        ],
        series_index=SERIES_INDEX,
        digest_provider={base_image: shared, r1_image: shared}.get,
    )

    assert [p.official_asset_variant for p in plan.prints] == ["base", "r1"]
    assert {p.official_artwork_sha256 for p in plan.prints} == {shared}
    assert {p.outcome for p in plan.prints} == {OUTCOME_CREATE}


def test_an_existing_base_print_does_not_absorb_a_new_rn_entry(db_session, op01, zoro):
    """An rN entry must not be matched against the base print that already
    exists - that would silently rewrite one printing into another."""
    make_print(db_session, zoro, op01, "base")
    r1_image = f"{CARDLIST}/OP01-001_r1.png"

    planned = plan_one(
        db_session,
        entry(entry_id="OP01-001_r1", image=r1_image),
        digests={r1_image: R1_DIGEST},
    )

    assert planned.official_asset_variant == "r1"
    assert planned.existing_card_print_id is None
    assert planned.outcome == OUTCOME_CREATE
    assert CREATE_CARD_PRINT in planned.creations


def test_an_existing_rn_print_is_recognised_as_no_change(db_session, op01, zoro):
    """The other direction: once an rN print exists, replanning it is a
    no-change rather than a second create."""
    existing = make_print(
        db_session, zoro, op01, "r1",
        artwork_key=R1_DIGEST, image_url=f"{CARDLIST}/OP01-001_r1.png",
    )
    r1_image = f"{CARDLIST}/OP01-001_r1.png"

    planned = plan_one(
        db_session,
        entry(entry_id="OP01-001_r1", image=r1_image),
        digests={r1_image: R1_DIGEST},
    )

    assert planned.existing_card_print_id == existing.id
    assert planned.outcome == OUTCOME_NO_CHANGE
    assert CREATE_CARD_PRINT not in planned.creations


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


# --- 11b. a sibling printing's NAME is a note, not a canonical conflict --------
#
# CanonicalCard.name_jp is the BASELINE name: what the card's own set
# published. Bandai republishes the name per entry, so a later printing may
# spell it differently - and across the complete 2026-08-22 JP corpus 17 card
# codes do, 16 formatting-only and one materially. None of them is evidence
# that the canonical card is wrong, and the exact published spelling is
# already carried verbatim on that print's official_name.


PRB02 = OfficialSeries(
    series_id="550902",
    display_name="プレミアムブースター【PRB-02】",
    official_code="PRB-02",
)


def _sibling_printing(db_session, name, *, series=PRB02, entry_id="OP01-001_p3"):
    """One later-printing occurrence of OP01-001, published under `series`."""
    planner = PrintImportPlanner(
        db_session,
        digest_provider={f"{CARDLIST}/{entry_id}.png": BASE_DIGEST}.get,
    )
    return planner.plan_entry(
        entry(
            entry_id=entry_id,
            image=f"{CARDLIST}/{entry_id}.png",
            products=(series.display_name,),
            name=name,
        ),
        series_index=(OP01_SERIES, series),
    )


def _name_note(planned) -> str:
    return next(r for r in planned.reasons if "printing's name" in r)


def test_an_nfkc_only_sibling_spelling_is_a_note_not_a_conflict(db_session, zoro):
    """'ロロノア・ゾロ' vs a full-width-folded rendering of the same name.

    The real corpus case is 'モンキー・D・ルフィ' against
    'モンキー・Ｄ・ルフィ' on 15 codes; the mechanism is identical.
    """
    planned = _sibling_printing(db_session, "ﾛﾛﾉｱ･ｿﾞﾛ")

    assert planned.outcome != OUTCOME_CONFLICT
    assert FLAG_CANONICAL_CARD_CONFLICT not in planned.flags
    assert FLAG_NAME_DIFFERS_BY_PRINTING in planned.flags
    assert "formatting-only" in _name_note(planned)


def test_a_material_sibling_spelling_is_still_only_a_note(db_session, zoro):
    """EB01-056: 'シャーロット・フランペ' in EB-01, 'シャーロット・フランぺ'
    in its OP-10 reprint - a genuinely different character, not formatting.

    Still descriptive. A material name difference on a later printing is a
    fact about that printing; it is not a second card, and it is not evidence
    that the canonical row is wrong.
    """
    planned = _sibling_printing(db_session, "ロロノア・ゾロウ")

    assert planned.outcome != OUTCOME_CONFLICT
    assert FLAG_CANONICAL_CARD_CONFLICT not in planned.flags
    assert FLAG_NAME_DIFFERS_BY_PRINTING in planned.flags
    assert "material" in _name_note(planned)


def test_a_sibling_name_difference_neither_creates_nor_rewrites_the_canonical_card(
    db_session, zoro
):
    """Neither kind may touch identity. No second canonical card is proposed,
    the exact print identity is unchanged, and name_jp is not rewritten."""
    before = zoro.name_jp

    for spelling in ("ﾛﾛﾉｱ･ｿﾞﾛ", "ロロノア・ゾロウ"):
        planned = _sibling_printing(db_session, spelling)

        assert planned.proposed_canonical_card is None
        assert CREATE_CANONICAL_CARD not in planned.creations
        assert planned.existing_canonical_card_id == zoro.id
        # The published spelling survives exactly, on the print.
        assert planned.official_name == spelling

    db_session.refresh(zoro)
    assert zoro.name_jp == before


def test_a_name_disagreement_on_the_baseline_occurrence_still_conflicts(
    db_session, op01, zoro
):
    """The card's OWN set is the occurrence name_jp is answerable against.

    A different name there is a real disagreement about the card, not about a
    printing, and it must still block.
    """
    planned = plan_one(db_session, entry(name="ロロノア・ゾロウ"))

    assert planned.outcome == OUTCOME_CONFLICT
    assert FLAG_CANONICAL_CARD_CONFLICT in planned.flags
    assert FLAG_NAME_DIFFERS_BY_PRINTING not in planned.flags
    assert any("name_jp" in r for r in planned.reasons)


# --- 11c. a card with NO original set (a promo) -------------------------------
#
# Bandai codes every family as <LETTERS><DIGITS>-<NUMBER> and reads the set
# code out of that prefix: ST-* Starter Deck, EB-* Extra Booster, PRB-*
# Premium Booster, OP-* Booster Pack. A promo's prefix carries no digits
# because a promo has no set, so `original_set_code` is NULL for it (migration
# d1c48b7f36ae) and no occurrence can ever be its baseline.


def test_the_promo_shape_is_recognised_from_the_published_code():
    """`P` is the only alphabetic-only prefix in the complete 2026-08-22 JP
    corpus (251 of 4962 entries); every other family carries digits."""
    assert is_promo_card_code("P-014") is True
    assert is_promo_card_code("P-107") is True
    for coded in ("OP01-001", "ST36-005", "PRB01-001", "EB01-012"):
        assert is_promo_card_code(coded) is False, coded


def test_a_malformed_code_is_not_mistaken_for_a_promo():
    """`original_set_code()` returns None for these too, which is exactly why
    the promo test is a separate, stricter question: a promo needs all three
    of a separator, an alphabetic-only prefix and a numeric suffix."""
    for junk in ("NOTACODE", "", "-014", "P-", "P-ABC"):
        assert original_set_code(junk) is None, junk
        assert is_promo_card_code(junk) is False, junk


@pytest.fixture()
def promo(db_session) -> CanonicalCard:
    """A promo Atlas already holds. No original set, by construction."""
    card = CanonicalCard(
        card_code="P-075",
        name_jp="モンキー・Ｄ・ルフィ",
        original_set_code=None,
        rarity="P",
        card_type="Character",
    )
    db_session.add(card)
    db_session.commit()
    return card


def _promo_printing(db_session, name, *, series=PRB02, entry_id="P-075_p2"):
    planner = PrintImportPlanner(
        db_session, digest_provider={f"{CARDLIST}/{entry_id}.png": BASE_DIGEST}.get
    )
    return planner.plan_entry(
        entry(
            entry_id=entry_id,
            card_code="P-075",
            image=f"{CARDLIST}/{entry_id}.png",
            products=(series.display_name,),
            name=name,
            rarity="P",
            category="CHARACTER",
        ),
        series_index=(OP01_SERIES, series),
    )


def test_a_formatting_only_sibling_of_a_promo_is_a_note_not_a_conflict(
    db_session, promo
):
    """THE 4C-3B REGRESSION. P-075's two coded PRB-02 occurrences publish
    'モンキー・Ｄ・ルフィ'; its two uncoded occurrences publish
    'モンキー・D・ルフィ' - a full-width vs ASCII D, formatting only.

    Before this fix the `baseline_set is None` branch made ANY difference a
    conflict, so making original_set_code nullable would have turned that
    sibling into a canonical-card conflict the moment its product resolved.
    It must stay descriptive."""
    planned = _promo_printing(db_session, "モンキー・D・ルフィ")

    assert planned.outcome != OUTCOME_CONFLICT
    assert FLAG_CANONICAL_CARD_CONFLICT not in planned.flags
    assert FLAG_NAME_DIFFERS_BY_PRINTING in planned.flags
    note = next(r for r in planned.reasons if "printing's name" in r)
    assert "formatting-only" in note
    # And it says what the canonical name was established from - not a set.
    assert "consensus across this card's coded occurrences" in note


def test_a_materially_different_promo_name_still_conflicts(db_session, promo):
    """Nothing settles a promo's canonical name, so a materially different
    spelling is a real disagreement about what the card is called. This is
    deliberately stricter than the has-a-baseline case, where a later
    printing's material difference is only descriptive."""
    planned = _promo_printing(db_session, "モンキー・Ｄ・ルフィウ")

    assert planned.outcome == OUTCOME_CONFLICT
    assert FLAG_CANONICAL_CARD_CONFLICT in planned.flags
    assert any("no original set" in r for r in planned.reasons)


def test_an_exactly_matching_promo_name_reports_nothing(db_session, promo):
    planned = _promo_printing(db_session, "モンキー・Ｄ・ルフィ")

    assert planned.outcome != OUTCOME_CONFLICT
    assert FLAG_NAME_DIFFERS_BY_PRINTING not in planned.flags
    assert FLAG_CANONICAL_CARD_CONFLICT not in planned.flags


def test_no_occurrence_of_a_promo_is_ever_treated_as_its_baseline(db_session, promo):
    """The failure mode the fix must not swap in: every occurrence becoming
    authoritative. No product code makes a promo occurrence the baseline."""
    for product_code in ("PRB-02", "ST-16", "OP-17", "P", "PROMO", None):
        assert PrintImportPlanner._is_baseline_occurrence(promo, product_code) is False
    assert PrintImportPlanner._baseline_set_code(promo) is None


def test_a_promo_rarity_difference_is_still_only_a_note(db_session, promo):
    """Unchanged by any of this: with no own set, `own_set` is False, so a
    differing rarity is descriptive - never a conflict."""
    planned = _promo_printing(db_session, "モンキー・Ｄ・ルフィ")
    planner_obj = PrintImportPlanner(db_session)
    diffs, notes = planner_obj._canonical_card_conflicts(
        promo, entry(card_code="P-075", name="モンキー・Ｄ・ルフィ", rarity="SPカード",
                     category="CHARACTER"),
        "PRB-02",
    )

    assert diffs == []
    assert [f for f, _ in notes] == [FLAG_RARITY_DIFFERS_BY_PRINTING]


def test_both_baseline_scoped_rules_resolve_the_baseline_the_same_way():
    """The name rule and the rarity rule are both scoped to the card's own-set
    occurrence, so they must agree about which occurrence that is.

    They used to resolve it by different means - the name rule through
    `_baseline_set_code` (column, falling back to the card code) and the rarity
    rule by reading `card.original_set_code` directly. Since d1c48b7f36ae made
    that column nullable for every row, a card with a NULL column and a
    readable card code is representable, and under the old code it was the
    baseline to one rule and not to the other: a name disagreement conflicted
    while a rarity disagreement on the same printing was only a note.
    """
    card = CanonicalCard(
        card_code="OP01-001", name_jp="ロロノア・ゾロ", original_set_code=None,
        rarity="L", card_type="Leader",
    )
    assert PrintImportPlanner._baseline_set_code(card) == "OP-01"
    assert PrintImportPlanner._is_baseline_occurrence(card, "OP-01") is True

    on_baseline = entry(name="ちがう名前", rarity="SR")
    conflicts, notes = PrintImportPlanner._canonical_card_conflicts(
        card, on_baseline, "OP-01"
    )

    # Both fields disagree on the SAME occurrence, so both must conflict.
    assert any(c.startswith("name_jp") for c in conflicts)
    assert any(c.startswith("rarity") for c in conflicts)
    assert notes == []


def test_a_card_with_no_own_set_never_reports_one_as_none(promo):
    """The note text is operator-facing. A promo has no own set, so it must
    not read 'for the card's own set (None)'."""
    _, notes = PrintImportPlanner._canonical_card_conflicts(
        promo,
        entry(card_code="P-075", name="モンキー・Ｄ・ルフィ", rarity="SPカード",
              category="CHARACTER"),
        "PRB-02",
    )

    assert [f for f, _ in notes] == [FLAG_RARITY_DIFFERS_BY_PRINTING]
    text = notes[0][1]
    assert "(None)" not in text
    assert "consensus across this card's coded occurrences" in text


def test_the_baseline_set_code_is_atlas_own_column_not_a_guess():
    """Atlas's own column wins over what the card code would derive; the
    derivation is the fallback for a card that has not been through the schema.
    Since d1c48b7f36ae the column is nullable, and None there means "this card
    is from no set" - which routes the name comparison to the promo rule
    above rather than to a baseline."""
    recorded = CanonicalCard(
        card_code="OP01-001", name_jp="x", original_set_code="ST-01",
        rarity="L", card_type="Leader",
    )
    # Atlas's own column wins over what the card code would derive.
    assert PrintImportPlanner._baseline_set_code(recorded) == "ST-01"
    assert PrintImportPlanner._is_baseline_occurrence(recorded, "ST-01") is True
    assert PrintImportPlanner._is_baseline_occurrence(recorded, "OP-01") is False
    # An uncoded product is never the baseline.
    assert PrintImportPlanner._is_baseline_occurrence(recorded, None) is False

    promo = CanonicalCard(
        card_code="P-014", name_jp="x", original_set_code=None,
        rarity="P", card_type="Character",
    )
    assert original_set_code("P-014") is None
    assert PrintImportPlanner._baseline_set_code(promo) is None


def test_card_type_still_conflicts_on_any_occurrence(db_session, zoro):
    """card_type describes the CARD, not the printing, so it is not
    baseline-scoped: a disagreement on a later printing still blocks."""
    entry_id = "OP01-001_p3"
    planner = PrintImportPlanner(
        db_session,
        digest_provider={f"{CARDLIST}/{entry_id}.png": BASE_DIGEST}.get,
    )
    planned = planner.plan_entry(
        entry(
            entry_id=entry_id,
            image=f"{CARDLIST}/{entry_id}.png",
            products=(PRB02.display_name,),
            category="CHARACTER",
        ),
        series_index=(OP01_SERIES, PRB02),
    )

    assert planned.outcome == OUTCOME_CONFLICT
    assert FLAG_CANONICAL_CARD_CONFLICT in planned.flags
    assert any("card_type" in r for r in planned.reasons)


def test_a_rarity_disagreement_on_the_cards_own_set_still_conflicts(
    db_session, op01, zoro
):
    """Unchanged by the name rule: the own-set occurrence is still where
    rarity is answerable, and a disagreement there still blocks."""
    planned = plan_one(db_session, entry(rarity="SR"))

    assert planned.outcome == OUTCOME_CONFLICT
    assert FLAG_CANONICAL_CARD_CONFLICT in planned.flags
    assert any("rarity" in r for r in planned.reasons)


def test_a_changed_asset_on_an_existing_print_is_still_blocking(db_session, op01, zoro):
    """Print identity is untouched by any of the above: a digest that no
    longer matches is still needs_review, and still never a second print."""
    make_print(db_session, zoro, op01, "base", artwork_key="c" * 64)
    planned = plan_one(
        db_session, entry(), digests={f"{CARDLIST}/OP01-001.png?260821": BASE_DIGEST}
    )

    assert planned.outcome == OUTCOME_NEEDS_REVIEW
    assert FLAG_ASSET_CHANGED in planned.flags
    assert planned.creations == ()


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


# --- query shape: bounded, not proportional to corpus size -------------------
#
# The planner is read-only, so every row it can observe is already committed
# before the first entry is planned. That is what makes a one-time prefetch
# equivalent to re-querying per entry - and it is why the count below must not
# grow with the corpus. A 4,962-entry run that issued four SELECTs per entry
# produced tens of thousands of round trips and could not finish over an SSH
# tunnel; these tests fail if that shape ever comes back.


def _count_select_statements(session):
    """Records every SELECT the session emits. Returns a mutable list."""
    statements: list[str] = []

    @event.listens_for(session.get_bind(), "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    return statements


def _corpus(size):
    """`size` distinct entries across distinct card codes, all unknown to Atlas."""
    return [
        entry(
            entry_id=f"OP01-{i:03d}",
            card_code=f"OP01-{i:03d}",
            image=f"{CARDLIST}/OP01-{i:03d}.png",
        )
        for i in range(1, size + 1)
    ]


def test_planning_query_count_does_not_grow_with_the_corpus(db_session, op01, zoro):
    """The real guarantee: 10x the entries must not mean 10x the queries."""
    small = _count_select_statements(db_session)
    plan_entries(
        db_session, _corpus(5), series_index=SERIES_INDEX, classify_mappings=False
    )
    small_count = len(small)

    # A fresh planner, so the prefetch is paid again rather than reused.
    db_session.expunge_all()
    large = _count_select_statements(db_session)
    plan_entries(
        db_session, _corpus(50), series_index=SERIES_INDEX, classify_mappings=False
    )
    # `large` was registered after the first run, so it holds only the second.
    large_count = len(large)

    assert small_count > 0, "the planner must actually read Atlas"
    assert large_count == small_count, (
        f"planning 50 entries issued {large_count} SELECTs where 5 entries issued "
        f"{small_count}: the query count is proportional to the corpus again"
    )


def test_planning_issues_a_small_bounded_number_of_selects(db_session, op01, zoro):
    """Concrete ceiling, so an accidental extra per-entry read is visible."""
    statements = _count_select_statements(db_session)
    plan_entries(
        db_session, _corpus(200), series_index=SERIES_INDEX, classify_mappings=False
    )
    assert len(statements) <= 4, (
        f"planning 200 entries issued {len(statements)} SELECTs; the planner reads "
        "release_products, canonical_cards and card_prints once each"
    )


def test_a_duplicate_exact_identity_is_still_refused_not_first_matched(
    db_session, op01, zoro
):
    """Prefetching must not collapse a duplicate into an arbitrary winner.

    The per-entry lookup was `scalar_one_or_none()`, which raises rather than
    picking. An index keyed one-row-per-identity would have silently answered
    with whichever row happened to be inserted first - turning a refusal into
    a plausible-looking plan. The bucket keeps both, so it still raises.
    """
    make_print(db_session, zoro, op01, "base", verification_status="unverified")
    make_print(db_session, zoro, op01, "base", verification_status="unverified")

    planner = PrintImportPlanner(db_session)
    with pytest.raises(MultipleResultsFound):
        planner.plan_entry(entry(), series_index=SERIES_INDEX)
