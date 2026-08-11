"""Offline, deterministic tests for snkrdunk_collector.extractor, against
the reduced real-shape product-page fixture (fixtures/product_page_reduced.html
- see spikes/snkrdunk-browser-feasibility for how it was derived from the
live page)."""

from pathlib import Path

from bs4 import BeautifulSoup

from snkrdunk_collector.extractor import (
    extract_product,
    extract_raw_conditions,
    find_condition_chip_container,
    find_embedded_json_blocks,
    find_main_product_image,
    find_product_ld_node,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
PRODUCT_URL = "https://snkrdunk.com/apparels/104428"


def _load_html() -> str:
    return (FIXTURES_DIR / "product_page_reduced.html").read_text(encoding="utf-8")


def _load_soup() -> BeautifulSoup:
    return BeautifulSoup(_load_html(), "html.parser")


def test_finds_the_single_condition_container():
    container, diagnostics = find_condition_chip_container(_load_soup())
    assert container is not None
    assert diagnostics["reason"] == "ok"
    assert diagnostics["chip_button_count"] == 16


def test_extracts_all_four_raw_conditions_with_correct_prices_and_nulls():
    result = extract_raw_conditions(_load_soup())
    conditions = result["conditions"]
    assert set(conditions.keys()) == {"A", "B", "C", "D"}
    assert conditions["A"]["price_jpy"] == 29000
    assert conditions["B"]["price_jpy"] == 24500
    assert conditions["C"]["price_jpy"] is None
    assert conditions["C"]["raw_text"] == "出品待ち"
    assert conditions["D"]["price_jpy"] is None


def test_raw_floor_chooses_lowest_available_raw_condition():
    result = extract_raw_conditions(_load_soup())
    assert result["raw_floor_jpy"] == 24500
    assert result["raw_floor_condition"] == "B"


def test_graded_conditions_never_appear_in_raw_conditions():
    result = extract_raw_conditions(_load_soup())
    graded_labels = {"PSA10", "PSA9", "PSA8以下", "BGS10 BL", "ARS10+", "他鑑定品"}
    assert graded_labels.isdisjoint(result["conditions"].keys())


def test_recommendation_carousel_price_never_leaks_into_raw_conditions():
    result = extract_raw_conditions(_load_soup())
    all_prices = [c["price_jpy"] for c in result["conditions"].values() if c["price_jpy"] is not None]
    assert 3450 not in all_prices  # the reco-carousel card's price


def test_missing_raw_listings_returns_null_floor_not_a_graded_price():
    html = """
    <div class="c__container">
      <button class="c__chip c__disabled"><p class="c__variant">A</p><p class="c__awaiting">出品待ち</p></button>
      <button class="c__chip c__disabled"><p class="c__variant">B</p><p class="c__awaiting">出品待ち</p></button>
      <button class="c__chip"><p class="c__variant">PSA10</p><p class="c__price">¥50,000</p></button>
    </div>
    """
    result = extract_raw_conditions(BeautifulSoup(html, "html.parser"))
    assert result["raw_floor_jpy"] is None
    assert result["conditions"]["A"]["price_jpy"] is None


def test_main_image_is_the_product_photo_not_a_generic_ogp_fallback():
    image_url, diagnostics = find_main_product_image(_load_soup())
    assert image_url == "https://cdn.snkrdunk.com/upload_bg_removed/20221121015111-0.webp?size=l"
    assert diagnostics["reason"] == "ok"


def test_json_ld_graph_wrapped_organization_website_no_product_node():
    embedded = find_embedded_json_blocks(_load_html())
    types = [n.get("@type") for n in embedded["ld_json_nodes"]]
    assert types == ["Organization", "WebSite"]
    assert find_product_ld_node(embedded["ld_json_nodes"]) is None


def test_json_ld_array_shape():
    html = '<script type="application/ld+json">[{"@type": "Organization"}, {"@type": "Product", "name": "x"}]</script>'
    embedded = find_embedded_json_blocks(html)
    product = find_product_ld_node(embedded["ld_json_nodes"])
    assert product is not None and product["name"] == "x"


def test_json_ld_plain_object_shape():
    html = '<script type="application/ld+json">{"@type": "Product", "name": "y"}</script>'
    embedded = find_embedded_json_blocks(html)
    product = find_product_ld_node(embedded["ld_json_nodes"])
    assert product is not None and product["name"] == "y"


def test_json_ld_parse_error_recorded_not_a_crash():
    html = '<script type="application/ld+json">{not valid json,,,}</script>'
    embedded = find_embedded_json_blocks(html)
    assert embedded["ld_json_parse_errors"] == 1
    assert embedded["ld_json_nodes"] == []


class TestExtractProductIntegration:
    def test_exact_print_match_succeeds_for_reduced_op01_001_fixture(self):
        result = extract_product(_load_html(), PRODUCT_URL, expected_card_code="OP01-001", expected_treatment="parallel")
        assert result["extraction_status"] == "extracted"
        assert result["fail_reasons"] == []
        extracted = result["extracted"]
        assert extracted["card_code"] == "OP01-001"
        assert extracted["rarity"] == "L"
        assert extracted["treatment"] == "parallel"
        assert extracted["page_language"] == "ja"
        assert extracted["raw_floor_jpy"] == 24500

    def test_card_code_conflict_fails_closed(self):
        result = extract_product(_load_html(), PRODUCT_URL, expected_card_code="OP01-002", expected_treatment="parallel")
        assert result["extraction_status"] == "fail_closed"
        assert any(r.startswith("card_code_conflict:") for r in result["fail_reasons"])

    def test_treatment_conflict_fails_closed(self):
        result = extract_product(_load_html(), PRODUCT_URL, expected_card_code="OP01-001", expected_treatment="normal")
        assert result["extraction_status"] == "fail_closed"
        assert any(r.startswith("treatment_conflict:") for r in result["fail_reasons"])

    def test_no_raw_price_fails_closed(self):
        html = """
        <html><head><title>ロロノア・ゾロ L-P [OP01-001]</title></head>
        <body><h1>ロロノア・ゾロ L-P [OP01-001]</h1>
        <img class="css__mainImage" src="https://cdn.snkrdunk.com/x.webp">
        <div class="c__container">
          <button class="c__chip c__disabled"><p class="c__variant">A</p><p class="c__awaiting">出品待ち</p></button>
        </div>
        </body></html>
        """
        result = extract_product(html, PRODUCT_URL, expected_card_code="OP01-001", expected_treatment="parallel")
        assert result["extraction_status"] == "fail_closed"
        assert "no_raw_condition_price_available" in result["fail_reasons"]


class TestObservedEvidenceRetention:
    """Every observed identity value a verification record needs must survive
    extraction - the 2026-08-11 audit found title/rarity/set/per-condition
    prices were computed and then discarded, leaving PASS unauditable."""

    def _extracted(self):
        return extract_product(
            _load_html(), PRODUCT_URL, expected_card_code="OP01-001", expected_treatment="parallel"
        )["extracted"]

    def test_observed_title_retained(self):
        assert "ロロノア・ゾロ" in self._extracted()["title"]

    def test_observed_card_name_retained_without_rarity_or_code(self):
        assert self._extracted()["card_name"] == "ロロノア・ゾロ"

    def test_observed_card_code_retained(self):
        assert self._extracted()["card_code"] == "OP01-001"

    def test_observed_rarity_retained(self):
        assert self._extracted()["rarity"] == "L"

    def test_observed_treatment_retained(self):
        assert self._extracted()["treatment"] == "parallel"

    def test_observed_page_language_retained(self):
        assert self._extracted()["page_language"] == "ja"

    def test_observed_release_text_retained(self):
        assert self._extracted()["release_text"] == "ブースターパックロマンスドーン"

    def test_observed_release_product_code_normalized_to_repo_convention(self):
        assert self._extracted()["release_product_code"] == "OP-01"

    def test_observed_primary_image_url_retained(self):
        image_url = self._extracted()["product_image_url"]
        assert image_url and image_url.startswith("https://")

    def test_complete_a_to_d_condition_values_retained_not_just_labels(self):
        """The regression that motivated this: logging list(conditions) kept
        only the keys, discarding every price and raw_text."""
        conditions = self._extracted()["conditions"]
        assert sorted(conditions) == ["A", "B", "C", "D"]
        for label, entry in conditions.items():
            assert entry["condition"] == label
            assert "price_jpy" in entry
            assert "raw_text" in entry

    def test_retained_conditions_carry_real_prices_and_awaiting_nulls(self):
        conditions = self._extracted()["conditions"]
        assert conditions["B"]["price_jpy"] == 24500
        # 出品待ち chips keep their source text but carry no numeric price.
        awaiting = [c for c in conditions.values() if c["price_jpy"] is None]
        assert awaiting, "fixture is expected to contain at least one 出品待ち chip"
        for entry in awaiting:
            assert entry["raw_text"] is not None
