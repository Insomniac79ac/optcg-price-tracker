"""SNKRDUNK renamed its CSS-module classes on 2026-10-26 (~08:29Z):
"styles-module-scss-module__slWKSa__mainImage" became "slWKSa_mainImage" on every
element. The same product must parse identically in every shape; tokens of any
other shape are never matched (the page is refused, not guessed)."""

from pathlib import Path
import re

from bs4 import BeautifulSoup
import pytest

from snkrdunk_collector.extractor import (
    _has_module_class,
    extract_product,
    find_condition_chip_container,
    find_main_product_image,
)

FIXTURE = (Path(__file__).parent / "fixtures/product_page_reduced.html").read_text(encoding="utf-8")
URL = "https://snkrdunk.com/apparels/104428"
MODULE = re.compile(r'(?<=class=")([^"]*)"')
HASHES = {"css1": "slWKSa", "css2": "jAqS3W", "css3": "bdsowG", "css4": "OZ3ksq"}


def reshape(html, style):
    """The fixture's css1__x classes in a live naming shape."""
    def token(t):
        m = re.fullmatch(r"(css\d)__(\w+)", t)
        if not m:
            return t
        h = HASHES[m.group(1)]
        return f"styles-module-scss-module__{h}__{m.group(2)}" if style == "until-2026-10-26" else f"{h}_{m.group(2)}"
    return MODULE.sub(lambda m: " ".join(token(t) for t in m.group(1).split()) + '"', html)


def parsed(html):
    soup = BeautifulSoup(html, "html.parser")
    result = extract_product(html, URL, expected_card_code="OP01-001", expected_treatment="parallel")
    container, diagnostics = find_condition_chip_container(soup)
    return {
        "status": result["extraction_status"],
        "fail_reasons": result["fail_reasons"],
        "raw_floor_jpy": result["extracted"]["raw_floor_jpy"],
        "raw_floor_condition": result["extracted"].get("raw_floor_condition"),
        "psa10": result["extracted"].get("psa10"),
        "image": find_main_product_image(soup)[0],
        "chips": diagnostics["chip_button_count"],
        "container": container is not None,
    }


@pytest.mark.parametrize("style", ["until-2026-10-26", "from-2026-10-26"])
def test_both_live_naming_shapes_parse_exactly_as_the_fixture(style):
    reshaped = reshape(FIXTURE, style)
    assert reshaped != FIXTURE
    if style == "from-2026-10-26":
        assert 'class="slWKSa_mainImage"' in reshaped
    assert parsed(reshaped) == parsed(FIXTURE)
    assert parsed(FIXTURE)["status"] == "extracted" and parsed(FIXTURE)["raw_floor_jpy"] == 24500


@pytest.mark.parametrize(
    "token,local,matched",
    [
        ("styles-module-scss-module__slWKSa__mainImage", "mainImage", True),
        ("slWKSa_mainImage", "mainImage", True),
        ("c__chip", "chip", True),
        ("mainImage", "mainImage", False),
        ("xmainImage", "mainImage", False),
        ("slWKSa_mainImageX", "mainImage", False),
        ("slWKSa___mainImage", "mainImage", False),
        ("foo_old_price", "price", False),
        ("slWKSa_variantImage", "variant", False),
        ("slWKSa_priceUnit", "price", False),
    ],
)
def test_only_css_module_tokens_for_that_local_name_match(token, local, matched):
    tag = BeautifulSoup(f'<p class="{token}"></p>', "html.parser").p
    assert _has_module_class(tag, local) is matched


def test_the_refused_live_markup_is_found_again():
    # Excerpt of a page refused on 2026-10-26 (snkr-page-check): the DOM main image is the
    # site placeholder, so the retained gallery decides; it is found as before.
    html = ('<li><button class="slWKSa_slideButton" aria-label="画像を全画面表示"><img alt="" '
            'fetchpriority="high" width="390" height="285" class="slWKSa_mainImage slWKSa_square" '
            'src="/_next/static/media/no-image.2w4_vu1cao4o4.webp"></button></li>')
    url, diagnostics = find_main_product_image(BeautifulSoup(html, "html.parser"))
    assert diagnostics["main_image_candidate_count"] == 1
    assert url == "/_next/static/media/no-image.2w4_vu1cao4o4.webp"  # no gallery props here
