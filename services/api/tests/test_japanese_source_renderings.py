"""The three Japanese storefront renderings added 2026-08-31, and the limits
that keep them from meaning more than they do.

WHY THEY EXIST. The collector fetches SNKRDUNK's JAPANESE page, because a jp
print's identity check demands `<html lang>` = ja. That page prints the release
name in Japanese, while the six pre-existing renderings are the ENGLISH labels
discovery reads from the candidate title on the English mirror. Different
strings, same products, different consumers - and until the Japanese ones were
declared the collector refused nine of thirty canary mappings with
`release_name_mismatch`.

WHAT THESE TESTS ARE GUARDING AGAINST. Not that the renderings work - that is
one assertion. The risk in adding a storefront spelling is that it reaches
further than intended: onto a neighbouring product, onto a coded product's
resolution, or into the approval gate's uncoded lookup. Each of those has its
own test below.
"""

import pytest
from sqlalchemy import select

from app.apply_source_renderings import (
    CONFIRM_PHRASE,
    SourceRenderingError,
    apply_renderings,
    plan_renderings,
)
from app.models import ReleaseProduct, ReleaseProductAlias
from app.services.exact_print_approval import resolve_uncoded_product_id
from app.services.uncoded_source_renderings import (
    SOURCE_RENDERING,
    UNCODED_SOURCE_RENDERINGS,
    rendering_for_label,
)

# The three added labels, exactly as observed on the Japanese pages in the
# 2026-08-31 live collector run (batch 2769f9740dc1).
JP_RENDERINGS = {
    "スタンダードバトルパックVol.1": "スタンダードバトルパック2022 Vol.1",
    "スタンダードバトルパックVol.2": "スタンダードバトルパック2022 Vol.2",
    "1st アニバーサリーセット": "1st ANNIVERSARY SET",
}

# Products that must NOT be reached by any of the three. Vol.3 is the dangerous
# neighbour: Bandai drops the year from its name, so it is the one product
# whose prose is closest to the Vol.1/Vol.2 storefront spellings.
NEIGHBOURS = (
    "スタンダードバトルパック Vol.3",
    "プレミアムカードコレクション 25周年エディション",
    "プレミアムカードコレクション - ベストセレクションvol.1 -",
)


@pytest.fixture()
def catalogue(db_session):
    """The uncoded products the renderings name, plus their neighbours, plus a
    CODED product - all as staging holds them."""
    db = db_session
    names = list(JP_RENDERINGS.values()) + list(NEIGHBOURS)
    for index, name in enumerate(names, start=1):
        db.add(
            ReleaseProduct(
                id=200 + index,
                source_catalogue="bandai_jp",
                official_code=None,
                display_name=name,
                first_seen_name=name,
                source_series_id=f"5509{index:02d}",
                source_url=f"https://example.test/{index}",
                verification_status="verified",
            )
        )
    # A coded product, to prove a source rendering can never answer for one.
    db.add(
        ReleaseProduct(
            id=300,
            source_catalogue="bandai_jp",
            official_code="OP-01",
            display_name="ブースターパック ROMANCE DAWN【OP-01】",
            first_seen_name="ブースターパック ROMANCE DAWN【OP-01】",
            source_series_id="569001",
            source_url="https://example.test/op01",
            verification_status="verified",
        )
    )
    db.commit()
    return db


def _product_id(db, name):
    return db.scalars(
        select(ReleaseProduct).where(ReleaseProduct.display_name == name)
    ).one().id


# --- the declared table -------------------------------------------------------


@pytest.mark.parametrize("label,product", sorted(JP_RENDERINGS.items()))
def test_each_new_rendering_is_declared_against_its_product(label, product):
    row = rendering_for_label("snkrdunk", label)
    assert row is not None, f"{label!r} is not declared"
    assert row.product_name == product
    assert row.observed_card_codes, "a rendering must carry the codes it was observed with"
    assert row.membership_relation in ("equal", "subset")
    assert len(row.evidence) > 80, "a rendering must carry real evidence, not a stub"


def test_lookup_is_exact_whole_label_equality(catalogue):
    """No normalisation, no fuzzy matching - the property the whole table
    rests on. The spaced variant an operator might type is NOT declared."""
    assert rendering_for_label("snkrdunk", "スタンダードバトルパック Vol.1") is None
    assert rendering_for_label("snkrdunk", "スタンダードバトルパックVol.") is None
    assert rendering_for_label("snkrdunk", "スタンダードバトルパックVol.11") is None
    assert rendering_for_label("snkrdunk", "1stアニバーサリーセット") is None
    assert rendering_for_label("yuyutei", "スタンダードバトルパックVol.1") is None


def test_the_pre_existing_english_renderings_are_unchanged(catalogue):
    """Adding Japanese rows must not disturb the six English ones."""
    english = {
        "Premium Card Collection -Best Selection vol.1-",
        "Premium Card Collection 25th Anniversary Edition",
        "Standard Battle Pack Vol.1",
        "Standard Battle Pack Vol.2",
        "Standard Battle Pack Vol.3",
        "1st ANNIVERSARY SET",
    }
    declared = {r.source_label for r in UNCODED_SOURCE_RENDERINGS}
    assert english <= declared
    assert len(UNCODED_SOURCE_RENDERINGS) == 9
    assert rendering_for_label("snkrdunk", "Standard Battle Pack Vol.1").product_name == (
        "スタンダードバトルパック2022 Vol.1"
    )


# --- writing them -------------------------------------------------------------


def test_planning_writes_nothing(catalogue):
    report = plan_renderings(catalogue)
    assert len(report.to_create) == 9
    assert report.applied is False
    assert catalogue.scalars(select(ReleaseProductAlias)).all() == []


def test_apply_without_the_phrase_is_refused(catalogue):
    with pytest.raises(SourceRenderingError, match="confirmation phrase"):
        apply_renderings(catalogue, labels=list(JP_RENDERINGS))
    assert catalogue.scalars(select(ReleaseProductAlias)).all() == []


def test_each_rendering_lands_on_exactly_its_own_product(catalogue):
    apply_renderings(catalogue, labels=list(JP_RENDERINGS), confirm=CONFIRM_PHRASE)
    rows = catalogue.scalars(select(ReleaseProductAlias)).all()
    assert len(rows) == 3
    for row in rows:
        assert row.alias_kind == SOURCE_RENDERING
        assert row.source_url is None
        assert row.product_id == _product_id(catalogue, JP_RENDERINGS[row.alias_name])


def test_no_neighbouring_product_gains_a_rendering(catalogue):
    """The Vol.3 product is the one whose Bandai name is closest to the Vol.1
    and Vol.2 storefront spellings; it must gain nothing from them."""
    apply_renderings(catalogue, labels=list(JP_RENDERINGS), confirm=CONFIRM_PHRASE)
    for name in NEIGHBOURS:
        pid = _product_id(catalogue, name)
        aliases = catalogue.scalars(
            select(ReleaseProductAlias).where(ReleaseProductAlias.product_id == pid)
        ).all()
        assert aliases == [], f"{name} unexpectedly gained {[a.alias_name for a in aliases]}"


def test_applying_twice_writes_nothing_the_second_time(catalogue):
    first = apply_renderings(catalogue, labels=list(JP_RENDERINGS), confirm=CONFIRM_PHRASE)
    assert len(first.to_create) == 3
    second = apply_renderings(catalogue, labels=list(JP_RENDERINGS), confirm=CONFIRM_PHRASE)
    assert second.to_create == []
    assert len(second.present) == 3
    assert len(catalogue.scalars(select(ReleaseProductAlias)).all()) == 3


def test_an_undeclared_label_cannot_be_written(catalogue):
    """The evidence standard is not optional: a label must be declared in the
    table, with its observed codes, before it can reach the database."""
    with pytest.raises(SourceRenderingError, match="not declared"):
        plan_renderings(catalogue, labels=["スタンダードバトルパックVol.9"])


def test_a_missing_or_ambiguous_product_refuses_the_whole_batch(catalogue):
    """Attaching a spelling to the wrong product is what would teach the
    collector to accept a wrong release, so it fails closed."""
    duplicate = ReleaseProduct(
        id=999,
        source_catalogue="bandai_jp",
        official_code=None,
        display_name="1st ANNIVERSARY SET",
        first_seen_name="1st ANNIVERSARY SET",
        source_series_id="559999",
        source_url="https://example.test/dup",
        verification_status="verified",
    )
    catalogue.add(duplicate)
    catalogue.commit()
    with pytest.raises(SourceRenderingError, match="must not be attached by guess"):
        apply_renderings(catalogue, labels=["1st アニバーサリーセット"], confirm=CONFIRM_PHRASE)
    assert catalogue.scalars(select(ReleaseProductAlias)).all() == []


# --- the limit that matters most ----------------------------------------------


def test_a_source_rendering_never_answers_for_a_coded_product(catalogue):
    """`resolve_uncoded_product_id` is restricted to `official_code IS NULL`,
    so a storefront spelling can never become a second route to a coded
    product - the route the worker's contents-based alias table owns."""
    catalogue.add(
        ReleaseProductAlias(
            product_id=300,
            alias_name="ロマンスドーン",
            alias_kind=SOURCE_RENDERING,
            source_url=None,
        )
    )
    catalogue.commit()
    assert resolve_uncoded_product_id(catalogue, "snkrdunk", "ロマンスドーン") is None


def test_the_new_japanese_labels_do_not_change_the_approval_gate(catalogue):
    """CONTAINMENT. The approval gate matches a candidate TITLE's parenthetical,
    which discovery reads from the English mirror - so it sees the English
    labels. The Japanese rows are for the collector, and adding them must not
    move a single approval decision.

    Asserted the direct way: the gate resolves each Japanese label to the
    product only if that exact string is what a candidate title carried, and
    the English label keeps resolving exactly as before.
    """
    apply_renderings(catalogue, labels=list(JP_RENDERINGS), confirm=CONFIRM_PHRASE)
    # The English label is not in this fixture's alias rows at all, so the gate
    # still resolves nothing for it - unchanged behaviour.
    assert resolve_uncoded_product_id(catalogue, "snkrdunk", "Standard Battle Pack Vol.1") is None
    # A Japanese label resolves only to its own product, never a neighbour.
    assert resolve_uncoded_product_id(catalogue, "snkrdunk", "スタンダードバトルパックVol.1") == (
        _product_id(catalogue, "スタンダードバトルパック2022 Vol.1")
    )
    assert resolve_uncoded_product_id(catalogue, "snkrdunk", "スタンダードバトルパック Vol.1") is None
    assert resolve_uncoded_product_id(catalogue, "snkrdunk", "スタンダードバトルパックVol.3") is None
