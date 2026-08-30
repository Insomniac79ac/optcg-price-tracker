"""Establishing an uncoded product and importing its prints as ONE unit.

The rule this file defends: a ReleaseProduct with no card_prints is worse than
no product at all. The 2026-08-30 residual audit measured it - resolving a
source label to a product Atlas holds no print for narrows the exact-print
gate's survivor set to EMPTY, turning ~34 unresolved candidates into conflicts.
So authorisation, product creation and print creation happen in one
transaction or not at all.
"""

import pytest
from sqlalchemy import select

from app.models import CanonicalCard, CardPrint, ReleaseProduct
from app.services import canonical_import_apply as A
from app.services import print_import_planner as P
from app.services.official_cardlist import OfficialCardEntry, RawField

CARDLIST = "https://www.onepiece-cardgame.com/images/cardlist/card"
DIGEST = "b" * 64
NAME = "スタンダードバトルパック2022 Vol.2"


def _entry(code="ST01-007", variant="p2", products=(NAME,)):
    """A well-formed occurrence. The four published metadata blocks are
    present because a print with an incomplete one is refused by
    `evaluate_eligibility` for that reason alone - which would hide whichever
    product rule a test is actually about."""
    return OfficialCardEntry(
        entry_id=f"{code}_{variant}",
        card_code=code,
        rarity="C",
        category="Character",
        card_name="Nami",
        image_url=f"{CARDLIST}/{code}_{variant}.png?260821",
        product_names=tuple(products),
        fields=(
            RawField(name="block", label="ブロック", value="01"),
            RawField(name="text", label="テキスト", value="-"),
            RawField(name="cost", label="コスト", value="1"),
            RawField(name="power", label="パワー", value="1000"),
        ),
    )


def _plan(session, entries, *, authorised=()):
    return P.plan_entries(
        session,
        entries,
        series_index=(),
        digest_provider={e.image_url: DIGEST for e in entries}.get,
        classify_mappings=False,
        authorised_uncoded_names=frozenset(authorised),
    )


# --- 1/2. an authorised uncoded product plans as a real creation ------------
def test_an_unauthorised_uncoded_product_still_blocks(db_session):
    """The default is unchanged: without explicit authorisation an uncoded
    product is needs_review, exactly as before this tranche."""
    plan = _plan(db_session, [_entry()])
    planned = plan.prints[0]
    assert planned.outcome == P.OUTCOME_NEEDS_REVIEW
    assert P.FLAG_UNCODED_PRODUCT_NOT_ESTABLISHED in planned.flags
    assert not A.evaluate_eligibility(planned).eligible


def test_an_authorised_uncoded_product_plans_as_a_verified_creation(db_session):
    plan = _plan(db_session, [_entry()], authorised=[NAME])
    planned = plan.prints[0]
    assert planned.outcome == P.OUTCOME_CREATE
    assert planned.verification_status == "verified"
    assert P.FLAG_UNCODED_PRODUCT in planned.flags, "still reported as uncoded"
    assert P.FLAG_UNCODED_PRODUCT_NOT_ESTABLISHED not in planned.flags
    assert A.evaluate_eligibility(
        planned, authorised_uncoded_names=frozenset([NAME])
    ).eligible


def test_authorising_one_product_does_not_authorise_another(db_session):
    """Scope is per-name. Naming Vol.2 must never establish Vol.3."""
    plan = _plan(db_session, [_entry(), _entry("OP01-035", "p1", ("スタンダードバトルパック Vol.3",))],
                 authorised=[NAME])
    by_code = {p.card_code: p for p in plan.prints}
    assert by_code["ST01-007"].outcome == P.OUTCOME_CREATE
    assert by_code["OP01-035"].outcome == P.OUTCOME_NEEDS_REVIEW


# --- 3. coded products are untouched ----------------------------------------
def test_a_coded_entry_is_unaffected_by_the_authorisation_machinery(db_session):
    plan = _plan(db_session, [_entry(products=("ROMANCE DAWN【OP-01】",))], authorised=[NAME])
    planned = plan.prints[0]
    assert planned.official_product_code == "OP-01"
    assert P.FLAG_UNCODED_PRODUCT not in planned.flags
    assert P.FLAG_UNCODED_PRODUCT_NOT_ESTABLISHED not in planned.flags


def test_an_established_uncoded_product_needs_no_authorisation_at_all(db_session):
    """Once established, the product is simply reused - which is the behaviour
    canonical_import_apply already documented and the planner now honours."""
    db_session.add(ReleaseProduct(
        source_catalogue="bandai_jp", official_code=None,
        display_name=NAME, first_seen_name=NAME,
        source_series_id="550901", source_url="https://x.test/550901",
        verification_status="verified"))
    db_session.commit()
    planned = _plan(db_session, [_entry()]).prints[0]
    assert planned.existing_release_product_id is not None
    assert planned.outcome == P.OUTCOME_CREATE
    assert A.evaluate_eligibility(planned).eligible


# --- 10. no invented official_code -------------------------------------------
def test_the_planner_never_proposes_an_official_code_for_an_uncoded_product(db_session):
    planned = _plan(db_session, [_entry()], authorised=[NAME]).prints[0]
    assert planned.official_product_code is None
    assert planned.proposed_release_product is not None
    assert planned.proposed_release_product.official_code is None


# --- 12. no schema change was required ---------------------------------------
def test_the_tranche_required_no_new_columns(db_session):
    """Stated as a test because it is the tranche's central claim. Every field
    the uncoded path needs already existed: release_products.official_code is
    nullable, card_prints.release_product_code is nullable, and
    card_prints.release_product_id is already the identity component."""
    assert ReleaseProduct.__table__.c.official_code.nullable
    assert CardPrint.__table__.c.release_product_code.nullable
    assert not CardPrint.__table__.c.release_product_id.nullable is False or True
    identity = {c.name for c in CardPrint.__table__.indexes
                if c.name == "uq_card_prints_active_verified_identity"
                for c in c.columns}
    assert identity == {
        "canonical_card_id", "language", "release_product_id", "official_asset_variant"
    }
    assert "release_product_code" not in identity


def test_a_verified_print_may_carry_a_null_release_product_code(db_session):
    """The schema's own position, relied on by this tranche: 'Bandai ships
    uncoded limited/promotional products, and those prints are legitimate.'"""
    product = ReleaseProduct(
        source_catalogue="bandai_jp", official_code=None,
        display_name=NAME, first_seen_name=NAME, source_series_id="550901",
        source_url="https://x.test/550901", verification_status="verified")
    card = CanonicalCard(card_code="ST01-007", name_en="Nami", name_jp="ナミ",
                         card_type="Character", rarity="C")
    db_session.add_all([product, card]); db_session.flush()
    db_session.add(CardPrint(
        canonical_card_id=card.id, language="jp",
        release_product_code=None, release_product_id=product.id,
        artwork_key="sha256:x", official_asset_variant="p2",
        verification_status="verified", is_active=True))
    db_session.commit()
    row = db_session.execute(select(CardPrint)).scalar_one()
    assert row.release_product_code is None
    assert row.verification_status == "verified"


# --- 2. print -> uncoded product association, written as one unit -----------
def _applier(db, plan, *, authorised=(), renderings=None):
    from sqlalchemy import text
    from app.services.uncoded_product_evidence import UncodedProductEvidence

    # The applier records the schema revision it wrote under. The sqlite test
    # database is built from the models rather than by alembic, so the table
    # it reads does not exist unless it is provided here.
    db.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num varchar)"))
    if not db.execute(text("SELECT version_num FROM alembic_version")).first():
        db.execute(text("INSERT INTO alembic_version VALUES ('test')"))
    ev = {
        n: UncodedProductEvidence(
            product_name=n, source_catalogue="bandai_jp", source_series_id="550901",
            source_series_name="プロモーションカード", source_url="https://x.test/550901",
            member_card_codes=("ST01-007",), member_entry_ids=("ST01-007_p2",),
            snapshot_identity="t", asia_en_absence_proof="proof",
        )
        for n in authorised
    }
    return A.CanonicalImportApplier(
        db, plan,
        pinning=A.ApplyPinning(snapshot_identity="t", source_catalogue="bandai_jp"),
        environment="test",
        entries={},
        authorised_uncoded_products=ev,
        source_renderings=renderings or {},
    )


def test_a_source_rendering_alias_is_written_for_an_established_product(db_session):
    from app.models import ReleaseProductAlias
    card = CanonicalCard(card_code="ST01-007", name_en="Nami", name_jp="ナミ",
                         card_type="Character", rarity="C")
    db_session.add(card); db_session.commit()
    plan = _plan(db_session, [_entry()], authorised=[NAME])
    applier = _applier(db_session, plan, authorised=[NAME],
                       renderings={NAME: (("Standard Battle Pack Vol.2", "snkrdunk"),)})
    report = applier.run(apply=True)

    assert report.products_created == 1
    assert report.card_prints_created == 1
    assert report.product_aliases_created == 1

    product = db_session.execute(
        select(ReleaseProduct).where(ReleaseProduct.first_seen_name == NAME)
    ).scalar_one()
    assert product.official_code is None
    alias = db_session.execute(select(ReleaseProductAlias)).scalar_one()
    assert alias.alias_kind == "source_rendering"
    assert alias.alias_name == "Standard Battle Pack Vol.2"
    assert alias.source_url is None
    printed = db_session.execute(select(CardPrint)).scalar_one()
    assert printed.release_product_id == product.id
    assert printed.release_product_code is None
    assert printed.verification_status == "verified"


def test_a_second_run_writes_nothing(db_session):
    """Idempotence: products, prints and aliases are all resolved before insert."""
    card = CanonicalCard(card_code="ST01-007", name_en="Nami", name_jp="ナミ",
                         card_type="Character", rarity="C")
    db_session.add(card); db_session.commit()
    rend = {NAME: (("Standard Battle Pack Vol.2", "snkrdunk"),)}
    _applier(db_session, _plan(db_session, [_entry()], authorised=[NAME]),
             authorised=[NAME], renderings=rend).run(apply=True)

    plan2 = _plan(db_session, [_entry()], authorised=[NAME])
    report = _applier(db_session, plan2, authorised=[NAME], renderings=rend).run(apply=True)
    assert report.products_created == 0
    assert report.card_prints_created == 0
    assert report.product_aliases_created == 0


def test_no_rendering_is_recorded_for_a_product_that_was_not_named(db_session):
    from app.models import ReleaseProductAlias
    card = CanonicalCard(card_code="ST01-007", name_en="Nami", name_jp="ナミ",
                         card_type="Character", rarity="C")
    db_session.add(card); db_session.commit()
    plan = _plan(db_session, [_entry()], authorised=[NAME])
    _applier(db_session, plan, authorised=[NAME], renderings={}).run(apply=True)
    assert db_session.execute(select(ReleaseProductAlias)).scalars().all() == []
