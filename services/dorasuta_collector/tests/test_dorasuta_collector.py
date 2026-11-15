"""Dorasuta collector on the kit: planning, writing and resolving, with fixture rows. No network.

The rows below are built from the MEASURED survey (SV §2.1): titles verbatim, product 471017's
three condition rows (状態A特価 ¥222 x1, 状態A ¥400 x11, 状態C ¥320 x32). The HTML parser and its
fixtures come with the first real list pages.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text

from app.models import CanonicalCard, CardPrint, PriceObservation, RawSnapshot, ReleaseProduct, Source, SourceCardMapping
from app.source_products.models import SourceProduct, SourceProductGroup, SourceProductVariant
from dorasuta_collector import config, run
from dorasuta_collector.resolve import resolve_all
from dorasuta_collector.writer import handle_page
from source_collector_kit.health import RunReport
from source_collector_kit.registry import ListingRow, ParsedPage

NOW = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)


def url(pid):
    return f"https://dorasuta.jp/onepiece-cardgame/product?pid={pid}"


# --- planning -----------------------------------------------------------------------------------


def test_series_and_page_urls():
    assert config.parse_series("7202:7, 7210") == (config.Series(7202, 7), config.Series(7210, 1))
    for bad in ("x", "7202:0", "7202:a", "1,1"):
        with pytest.raises(ValueError):
            config.parse_series(bad)
    assert config.list_page_url(7202) == "https://dorasuta.jp/onepiece-cardgame/product-list?sid=7202"
    assert config.list_page_url(7202, 3).endswith(
        "sid=7202&form110200_mode=search&form110200_params%5B0%5D=pager&form110200_params%5B1%5D=3"
    )


def test_light_mode_fetches_page_one_daily_and_every_page_within_six_days():
    series = config.parse_series("7202:7,7203:4")
    seen = set()
    for day in range(config.SWEEP_DAYS):
        pages = config.plan_pages(series, day)
        assert pages[:2] == [config.list_page_url(7202), config.list_page_url(7203)]
        seen.update(pages)
    assert len(seen) == 7 + 4
    sixty = config.parse_series(",".join(f"{7000 + i}:7" for i in range(30)) + "," +
                                ",".join(f"{8000 + i}:2" for i in range(30)))
    daily = [len(config.plan_pages(sixty, d)) for d in range(config.SWEEP_DAYS)]
    assert max(daily) + 1 <= config.MAX_REQUESTS_PER_RUN  # ESTIMATE about 105 a day in the plan


def test_a_run_refuses_before_any_request(monkeypatch, capsys):
    monkeypatch.delenv("SOURCE_COLLECTOR_CONTACT", raising=False)
    assert run.main([]) == 2
    monkeypatch.setenv("SOURCE_COLLECTOR_CONTACT", "bot@cardpirate.test.dev")
    monkeypatch.setenv(config.SERIES_ENV, "7202:7")
    assert run.main([]) == 2  # no parser is registered for dorasuta-list-v1 yet
    assert "ParserUnavailable" in capsys.readouterr().out


# --- writing ------------------------------------------------------------------------------------


@pytest.fixture()
def shop(db):
    source = Source(name="dorasuta", base_url="https://dorasuta.jp")
    db.add(source)
    op05 = ReleaseProduct(source_catalogue="bandai_jp", official_code="OP-05", display_name="OP-05",
                          first_seen_name="OP-05", source_series_id="s-op05", source_url="https://b.test/op05",
                          verification_status="verified")
    db.add(op05)
    db.flush()
    family = CanonicalCard(card_code="OP05-119", name_en="Luffy", card_type="Character")
    db.add(family)
    db.flush()
    prints = {}
    for variant in ("base", "p1"):
        row = CardPrint(canonical_card_id=family.id, language="jp", release_product_code="OP-05",
                        release_product_id=op05.id, artwork_key=f"sha256:{variant}", official_asset_variant=variant,
                        verification_status="verified", is_active=True)
        db.add(row)
        prints[variant] = row
    raw = RawSnapshot(source_id=source.id, source_url=config.list_page_url(7202), fetched_at=NOW, http_status=200,
                      content_hash="0" * 64, raw_content="<html/>", parser_version=config.PARSER_VERSION)
    db.add(raw)
    db.commit()
    return source, op05, prints, raw


def page(*rows, title="ブースターパック 新時代の主役【OP-05】"):
    return ParsedPage(rows=tuple(rows), group_key="sid-7202", group_title=title)


def report():
    return RunReport(source="dorasuta", parser_version=config.PARSER_VERSION, started_at=NOW)


PLAIN = "モンキー・D・ルフィ(SEC)(OP05-119)"
PARALLEL = "モンキー・D・ルフィ(SEC/パラレル)(OP05-119)"


def test_rows_become_products_groups_and_one_variant_per_condition(db, shop):
    source, _, _, raw = shop
    r = report()
    handle_page(db, source, page(
        ListingRow("471017", url(471017), PLAIN, "状態A特価", 222, 1),
        ListingRow("471017", url(471017), PLAIN, "状態A", 400, 11),
        ListingRow("471017", url(471017), PLAIN, "状態C(プレイ用)", 320, 32, sold_out=True),
        ListingRow("471018", url(471018), PARALLEL, "状態S", 9000, 1),
        ListingRow("x", "https://dorasuta.jp/onepiece-cardgame/series-list", "?", "状態A", 1, 1),
    ), raw, r)
    db.commit()
    product = db.scalar(select(SourceProduct).where(SourceProduct.source_product_key == "471017"))
    assert (product.canonical_listing_identity, product.parsed_code, product.listing_kind) == (
        "dorasuta:471017", "OP05-119", "plain")
    assert product.match_status == "pending" and product.group_keys == ["sid-7202"]
    variants = {v.grade_key: (v.last_price_jpy, v.stock) for v in db.scalars(select(SourceProductVariant))}
    assert variants == {"raw:damaged": (222, 1), "raw:A": (400, 11), "raw:play": (320, 0)}
    group = db.scalar(select(SourceProductGroup))
    assert (group.group_key, group.release_product_id, group.kind) == ("sid-7202", None, "series")
    assert r.products_new == 2 and r.variants_written == 3
    assert r.outcomes == {"row_condition_unknown": 1, "row_not_a_listing": 1}
    assert db.query(PriceObservation).count() == 0


def test_resolution_needs_a_reviewed_group_release_and_never_runs_mid_page(db, shop):
    source, op05, prints, raw = shop
    handle_page(db, source, page(
        ListingRow("471017", url(471017), PLAIN, "状態A", 400, 11),
        ListingRow("471018", url(471018), PARALLEL, "状態A", 9000, 1),
    ), raw, report())
    db.commit()
    assert resolve_all(db) == {"release_group_unresolved": 2}
    db.scalar(select(SourceProductGroup)).release_product_id = op05.id
    db.commit()
    assert resolve_all(db) == {"exact": 2}
    by_key = {p.source_product_key: p.card_print_id for p in db.scalars(select(SourceProduct))}
    assert by_key == {"471017": prints["base"].id, "471018": prints["p1"].id}


def test_only_a_mapped_exact_raw_a_row_writes_an_observation(db, shop):
    source, op05, prints, raw = shop
    db.add(SourceProductGroup(source_id=source.id, group_key="sid-7202", url="u", title="OP-05", kind="series",
                              release_product_id=op05.id))
    db.commit()
    rows = (ListingRow("471017", url(471017), PLAIN, "状態A", 400, 11, on_sale=True),
            ListingRow("471017", url(471017), PLAIN, "状態A特価", 222, 1))
    handle_page(db, source, page(*rows), raw, report())
    db.commit()
    resolve_all(db)
    db.commit()
    handle_page(db, source, page(*rows), raw, report())
    assert db.query(PriceObservation).count() == 0  # exact, but no approved mapping yet
    mapping = SourceCardMapping(source_id=source.id, card_print_id=prints["base"].id, source_card_id="OP05-119",
                                source_url=url(471017), canonical_source_listing_identity="dorasuta:471017",
                                review_status="approved", is_active=True, manual_verified=True)
    db.add(mapping)
    db.commit()
    r = report()
    handle_page(db, source, page(*rows), raw, r)
    db.commit()
    observation = db.query(PriceObservation).one()
    assert (observation.price_jpy, observation.price_type, observation.card_print_id) == (400, "sell", prints["base"].id)
    assert (observation.promotion_state, observation.stock_status, observation.raw_snapshot_id) == ("sale", "in_stock", raw.id)
    assert r.observations_written == 1
    assert db.execute(text("SELECT grade_key FROM price_observations")).scalar_one() == "raw:A"


def test_two_current_mappings_for_one_listing_write_nothing(db, shop):
    source, op05, prints, raw = shop
    db.add(SourceProductGroup(source_id=source.id, group_key="sid-7202", url="u", title="OP-05", kind="series",
                              release_product_id=op05.id))
    db.commit()
    rows = (ListingRow("471017", url(471017), PLAIN, "状態A", 400, 11),)
    handle_page(db, source, page(*rows), raw, report())
    db.commit()
    resolve_all(db)
    # The same listing written two ways: the table's (source_id, source_url) key cannot see the clash.
    for print_key, listing_url in (("base", url(471017)), ("p1", url(471017) + "&ref=list")):
        db.add(SourceCardMapping(source_id=source.id, card_print_id=prints[print_key].id, source_card_id="OP05-119",
                                 source_url=listing_url, review_status="approved", is_active=True,
                                 manual_verified=True))
    db.commit()
    handle_page(db, source, page(*rows), raw, report())
    assert db.query(PriceObservation).count() == 0


def test_graded_titles_stay_in_variants(db, shop):
    source, _, _, raw = shop
    handle_page(db, source, page(ListingRow("9", url(9), "PSA10鑑定 ルフィ(SEC)(OP05-119)", None, 50000, 1)),
                raw, report())
    db.commit()
    assert db.scalar(select(SourceProductVariant)).grade_key == "graded:PSA:10"
    assert db.scalar(select(SourceProduct)).listing_kind == "graded"
