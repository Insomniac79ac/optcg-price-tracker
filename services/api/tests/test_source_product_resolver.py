"""Exact-print resolution for new-source products (plan §2.3). Fixtures only."""

from datetime import datetime, timezone

import pytest

from app.models import CanonicalCard, CardPrint, ReleaseProduct, Source
from app.source_products import dorasuta_rules
from app.source_products.models import SourceProduct, SourceProductGroup, SourceVariantRendering
from app.source_products.resolver import (
    QUARANTINE_FOIL_WITHOUT_FOIL_PRINT,
    QUARANTINE_KIND_CONTRADICTS_PRINT,
    QUARANTINE_LISTING_GRADED,
    QUARANTINE_MARKER_UNRENDERED,
    QUARANTINE_NO_CANDIDATE,
    QUARANTINE_RELEASE_UNCODED,
    QUARANTINE_RELEASE_UNRESOLVED,
    QUARANTINE_RENDERINGS_CONFLICT,
    REFUSE_SEALED,
    REFUSE_TWO_RELEASES,
    Rendering,
    apply_resolution,
    resolve_product,
    resolve_stored_product,
)
from app.services.exact_print_approval import REFUSAL_AMBIGUOUS, REFUSAL_NO_SOURCE_CARD_CODE

URL = "https://dorasuta.jp/onepiece/product?pid=1"
IDENTITY = "dorasuta:1"


def _release(db, code):
    row = ReleaseProduct(
        source_catalogue="bandai_jp", official_code=code, display_name=code or "uncoded",
        first_seen_name=code or "uncoded", source_series_id=f"series-{code}",
        source_url=f"https://bandai.example.test/{code}", verification_status="verified",
    )
    db.add(row)
    db.flush()
    return row


def _family(db, code):
    row = db.query(CanonicalCard).filter_by(card_code=code).one_or_none()
    if row is None:
        row = CanonicalCard(card_code=code, name_en=code, card_type="Character")
        db.add(row)
        db.flush()
    return row


def _print(db, code, release, variant="base", *, rarity=None, treatment=None, active=True):
    row = CardPrint(
        canonical_card_id=_family(db, code).id, language="jp",
        release_product_code=release.official_code, release_product_id=release.id,
        artwork_key=f"sha256:{code}:{release.id}:{variant}", official_asset_variant=variant,
        official_rarity=rarity, treatment=treatment, verification_status="verified", is_active=active,
    )
    db.add(row)
    db.flush()
    return row


def _resolve(db, title, releases, *, renderings=None, same_kind=(IDENTITY,), held=()):
    return resolve_product(
        db, source_name="dorasuta", url=URL, listing_identity=IDENTITY,
        parsed=dorasuta_rules.parse_title(title), release_product_ids=[r.id for r in releases],
        renderings=renderings or {}, same_kind_listings=same_kind, prints_held_elsewhere=held,
    )


def test_only_print_in_release_is_exact_through_the_shared_gate(db_session):
    op01 = _release(db_session, "OP-01")
    base = _print(db_session, "OP01-016", op01)
    result = _resolve(db_session, "ナミ(R)(OP01-016)", [op01])
    assert result.is_exact and result.card_print_id == base.id
    assert "product OP-01" in result.evidence_used


def test_release_comes_from_the_group_not_the_code_prefix(db_session):
    op09, op11 = _release(db_session, "OP-09"), _release(db_session, "OP-11")
    _print(db_session, "OP09-004", op09)
    reprint = _print(db_session, "OP09-004", op11, "p1", rarity="SPカード")
    result = _resolve(db_session, "シャンクス(SP/SR)(OP09-004)", [op11])
    assert result.is_exact and result.card_print_id == reprint.id


def test_two_way_unique_plain_and_parallel(db_session):
    op05 = _release(db_session, "OP-05")
    base = _print(db_session, "OP05-119", op05)
    parallel = _print(db_session, "OP05-119", op05, "p1")
    plain = _resolve(db_session, "ルフィ(SEC)(OP05-119)", [op05])
    assert plain.is_exact and plain.card_print_id == base.id
    assert plain.evidence_used[-1] == "unique plain listing and unique plain print in release"
    par = _resolve(db_session, "ルフィ(SEC/パラレル)(OP05-119)", [op05])
    assert par.is_exact and par.card_print_id == parallel.id


def test_kind_rule_needs_one_listing_of_the_kind(db_session):
    op05 = _release(db_session, "OP-05")
    _print(db_session, "OP05-119", op05)
    _print(db_session, "OP05-119", op05, "p1")
    result = _resolve(db_session, "ルフィ(SEC)(OP05-119)", [op05], same_kind=(IDENTITY, "dorasuta:2"))
    assert result.match_status == "quarantined" and result.refusal_code == REFUSAL_AMBIGUOUS


def test_kind_rule_needs_one_print_of_the_kind(db_session):
    op09 = _release(db_session, "OP-09")
    _print(db_session, "OP09-118", op09)
    _print(db_session, "OP09-118", op09, "p1")
    p2 = _print(db_session, "OP09-118", op09, "p2")
    title = "ロジャー(SEC/スーパーパラレル)(OP09-118)"
    assert _resolve(db_session, title, [op09]).refusal_code == REFUSAL_AMBIGUOUS
    rendered = _resolve(db_session, title, [op09], renderings={"スーパーパラレル": Rendering("p2")})
    assert rendered.is_exact and rendered.card_print_id == p2.id
    assert "asset variant p2" in rendered.evidence_used


def test_kind_rule_never_takes_a_print_held_by_another_product(db_session):
    op05 = _release(db_session, "OP-05")
    base = _print(db_session, "OP05-119", op05)
    _print(db_session, "OP05-119", op05, "p1")
    result = _resolve(db_session, "ルフィ(SEC)(OP05-119)", [op05], held=(base.id,))
    assert result.refusal_code == REFUSAL_AMBIGUOUS


def test_foil_matches_only_a_foil_print(db_session):
    prb = _release(db_session, "PRB-01")
    _print(db_session, "PRB01-001", prb)
    result = _resolve(db_session, "ゾロ(L/ラメフォイル)(PRB01-001)", [prb], renderings={})
    # ラメフォイル is a marker; without a rendering it stops first.
    assert result.refusal_code == QUARANTINE_MARKER_UNRENDERED
    no_foil = _resolve(db_session, "ゾロ(L/ラメフォイル)(PRB01-001)", [prb],
                       renderings={"ラメフォイル": Rendering("base")})
    assert no_foil.refusal_code == QUARANTINE_FOIL_WITHOUT_FOIL_PRINT


def test_foil_resolves_to_the_foil_print(db_session):
    prb = _release(db_session, "PRB-01")
    _print(db_session, "PRB01-001", prb)
    foil = _print(db_session, "PRB01-001", prb, "p1", treatment="ラメフォイル")
    result = _resolve(db_session, "ゾロ(L/ラメフォイル)(PRB01-001)", [prb],
                      renderings={"ラメフォイル": Rendering("p1")})
    assert result.is_exact and result.card_print_id == foil.id


def test_parallel_listing_with_only_a_base_print_is_quarantined(db_session):
    op01 = _release(db_session, "OP-01")
    _print(db_session, "OP01-016", op01)
    result = _resolve(db_session, "ナミ(R/パラレル)(OP01-016)", [op01])
    assert result.refusal_code == QUARANTINE_KIND_CONTRADICTS_PRINT


def test_markers_need_reviewed_renderings(db_session):
    op09 = _release(db_session, "OP-09")
    gold = _print(db_session, "OP09-004", op09, "p3", rarity="SPカード")
    title = "シャンクス(SP/SR/金箔)(OP09-004)【3周年SP】"
    assert _resolve(db_session, title, [op09]).refusal_code == QUARANTINE_MARKER_UNRENDERED
    partial = {"金箔": Rendering("p3")}
    assert _resolve(db_session, title, [op09], renderings=partial).refusal_code == QUARANTINE_MARKER_UNRENDERED
    full = {"金箔": Rendering("p3"), "【3周年SP】": Rendering("p3")}
    assert _resolve(db_session, title, [op09], renderings=full).card_print_id == gold.id
    clash = {"金箔": Rendering("p3"), "【3周年SP】": Rendering("p4")}
    assert _resolve(db_session, title, [op09], renderings=clash).refusal_code == QUARANTINE_RENDERINGS_CONFLICT


def test_bare_promo_p_never_decides_a_kind(db_session):
    promo = _release(db_session, "P-PROMO")
    _print(db_session, "P-001", promo)
    _print(db_session, "P-001", promo, "p1")
    assert _resolve(db_session, "ルフィ(P)(P-001)", [promo]).refusal_code == REFUSAL_AMBIGUOUS


@pytest.mark.parametrize(
    "title, releases, status, code",
    [
        ("ナミ(R)", 1, "quarantined", REFUSAL_NO_SOURCE_CARD_CODE),
        ("ナミ(R)(OP01-016)", 0, "quarantined", QUARANTINE_RELEASE_UNRESOLVED),
        ("ナミ(R)(OP01-016)", 2, "refused", REFUSE_TWO_RELEASES),
        ("ブースター(未開封)(OP01-016)", 1, "refused", REFUSE_SEALED),
        ("PSA10鑑定 ナミ(R)(OP01-016)", 1, "quarantined", QUARANTINE_LISTING_GRADED),
    ],
)
def test_shared_refusals(db_session, title, releases, status, code):
    rows = [_release(db_session, "OP-01"), _release(db_session, "OP-02")][:releases]
    if rows:
        _print(db_session, "OP01-016", rows[0])
    result = _resolve(db_session, title, rows)
    assert (result.match_status, result.refusal_code, result.card_print_id) == (status, code, None)


def test_uncoded_release_and_empty_release(db_session):
    uncoded = _release(db_session, None)
    assert _resolve(db_session, "ナミ(R)(OP01-016)", [uncoded]).refusal_code == QUARANTINE_RELEASE_UNCODED
    op02 = _release(db_session, "OP-02")
    _print(db_session, "OP01-016", _release(db_session, "OP-01"))
    assert _resolve(db_session, "ナミ(R)(OP01-016)", [op02]).refusal_code == QUARANTINE_NO_CANDIDATE


def test_inactive_print_is_not_a_candidate(db_session):
    op01 = _release(db_session, "OP-01")
    _print(db_session, "OP01-016", op01, active=False)
    assert _resolve(db_session, "ナミ(R)(OP01-016)", [op01]).refusal_code == QUARANTINE_NO_CANDIDATE


def _stored(db, source, pid, title, groups, status="pending", card_print_id=None):
    parsed = dorasuta_rules.parse_title(title)
    row = SourceProduct(
        source_id=source.id, source_product_key=str(pid), canonical_listing_identity=f"dorasuta:{pid}",
        url=f"https://dorasuta.jp/onepiece/product?pid={pid}", group_keys=list(groups), name=title,
        parsed_code=parsed.card_code, rarity=parsed.rarity, variant_markers=list(parsed.markers),
        listing_kind=parsed.kind, match_status=status, card_print_id=card_print_id,
        refusal_code="manual_check" if status in {"quarantined", "refused"} else None,
    )
    db.add(row)
    db.flush()
    return row, parsed


def test_stored_products_use_their_groups_renderings_and_siblings(db_session):
    source = Source(name="dorasuta", base_url="https://dorasuta.jp")
    db_session.add(source)
    db_session.flush()
    op05 = _release(db_session, "OP-05")
    base = _print(db_session, "OP05-119", op05)
    parallel = _print(db_session, "OP05-119", op05, "p1")
    db_session.add(SourceProductGroup(source_id=source.id, group_key="sid-5", url="https://dorasuta.jp/x",
                                      title="OP-05", kind="pack", release_product_id=op05.id))
    db_session.add(SourceVariantRendering(source_id=source.id, marker_text="★", official_asset_variant="p1",
                                          reviewed_by="owner", reviewed_at=datetime.now(timezone.utc)))
    db_session.flush()
    plain, plain_parsed = _stored(db_session, source, 1, "ルフィ(SEC)(OP05-119)", ["sid-5"])
    star, star_parsed = _stored(db_session, source, 2, "ルフィ(SEC★/パラレル)(OP05-119)", ["sid-5"])

    result = resolve_stored_product(db_session, plain, plain_parsed)
    assert result.card_print_id == base.id
    assert apply_resolution(plain, result) and plain.match_status == "exact"
    starred = resolve_stored_product(db_session, star, star_parsed)
    assert starred.card_print_id == parallel.id

    # A second plain product of the same code and release breaks the two-way rule for both.
    other, _ = _stored(db_session, source, 3, "ルフィ(SEC)(OP05-119)", ["sid-5"])
    plain.match_status, plain.card_print_id = "pending", None
    assert resolve_stored_product(db_session, plain, plain_parsed).refusal_code == REFUSAL_AMBIGUOUS
    db_session.flush()


def test_manual_match_always_wins():
    product = SourceProduct(match_status="manual", card_print_id=7)
    from app.source_products.resolver import Resolution

    assert not apply_resolution(product, Resolution("quarantined", refusal_code=REFUSAL_AMBIGUOUS))
    assert (product.match_status, product.card_print_id) == ("manual", 7)
