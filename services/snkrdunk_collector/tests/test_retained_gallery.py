import json
import pytest
from bs4 import BeautifulSoup
from snkrdunk_collector.extractor import find_main_product_image, extract_product

URL = "https://cdn.snkrdunk.com/upload_bg_removed/88e7414d-449b-4ce5-bf15-b61311fc8865.webp"
PLACEHOLDER = "/_next/static/media/no-image.2w4_vu1cao4o4.webp"


def html(
    *,
    images=None,
    variants=None,
    module="ApparelGalleryContainer",
    duplicate=False,
    src=PLACEHOLDER,
    malformed=False,
):
    props = {
        "mainImages": images if images is not None else [{"src": URL}],
        "variantSources": (
            variants
            if variants is not None
            else [
                {"productId": 218861, "imageUrl": URL},
                {
                    "productId": 274102,
                    "imageUrl": "https://cdn.snkrdunk.com/upload_bg_removed/other.webp",
                },
            ]
        ),
    }
    payload = (
        "71:I"
        + json.dumps([1, ["chunk.js"], module])
        + "\n43:"
        + json.dumps(["$", "$L71", None, props])
        + "\n"
    )
    if duplicate:
        payload += "44:" + json.dumps(["$", "$L71", None, props]) + "\n"
    script = "self.__next_f.push(" + json.dumps([1, payload]) + ")"
    if malformed:
        script = 'self.__next_f.push([1,"bad])'
    return f'<html lang="ja"><title>ウル頭銃 UC [OP01-118] (ブースターパック ロマンスドーン)</title><h1>ウル頭銃</h1><img class="css__mainImage" src="{src}"><script>{script}</script></html>'


def test_primary_server_gallery_survives_site_placeholder_replacement():
    url, diagnostic = find_main_product_image(BeautifulSoup(html(), "html.parser"))
    assert url == URL
    assert diagnostic["reason"] == "retained_single_primary_gallery"
    result = extract_product(
        html(), "https://snkrdunk.com/apparels/142693", "OP01-118", None
    )
    assert result["extracted"]["product_image_url"] == URL
    assert result["extracted"]["raw_floor_jpy"] is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"images": []},
        {"images": [{"src": URL}, {"src": URL}]},
        {
            "variants": [
                {
                    "productId": 218861,
                    "imageUrl": "https://cdn.snkrdunk.com/upload_bg_removed/other.webp",
                }
            ]
        },
        {"variants": [{"productId": True, "imageUrl": URL}]},
        {
            "variants": [
                {"productId": 1, "imageUrl": URL},
                {"productId": 2, "imageUrl": URL},
            ]
        },
        {"module": "RecommendationGallery"},
        {"duplicate": True},
        {"malformed": True},
        {"images": [{"src": "https://evil.test/upload_bg_removed/primary.webp"}]},
        {"images": [{"src": URL + "?redirect=other"}]},
    ],
)
def test_absent_ambiguous_or_unscoped_gallery_preserves_refusal(kwargs):
    url, diagnostic = find_main_product_image(
        BeautifulSoup(html(**kwargs), "html.parser")
    )
    assert url == PLACEHOLDER
    assert diagnostic["selector"] == 'img[class$="__mainImage"]'


def test_real_dom_primary_keeps_precedence():
    url, diagnostic = find_main_product_image(
        BeautifulSoup(html(src=URL + "?size=l"), "html.parser")
    )
    assert url == URL + "?size=l"
    assert diagnostic["selector"] == 'img[class$="__mainImage"]'


def test_missing_or_duplicate_primary_dom_is_not_rescued_by_embedded_data():
    for body in (
        html().replace('class="css__mainImage"', 'class="relatedImage"'),
        html().replace(
            "</html>", '<img class="other__mainImage" src="' + PLACEHOLDER + '"></html>'
        ),
    ):
        assert find_main_product_image(BeautifulSoup(body, "html.parser"))[0] is None


def test_unrelated_prices_and_variant_images_never_supply_primary_or_price():
    body = html(images=[]).replace(
        "</html>",
        '<script type="application/ld+json">{"@type":"Product","image":"'
        + URL
        + '","offers":{"price":999999}}</script></html>',
    )
    result = extract_product(
        body, "https://snkrdunk.com/apparels/142693", "OP01-118", None
    )
    assert result["extracted"]["product_image_url"] == PLACEHOLDER
    assert result["extracted"]["raw_floor_jpy"] is None


def test_conflicting_flight_record_identity_fails_closed():
    body = html()
    conflicting = "71:I" + json.dumps([1, ["other.js"], "RecommendationGallery"]) + "\n"
    body = body.replace(
        "</html>",
        "<script>self.__next_f.push("
        + json.dumps([1, conflicting])
        + ")</script></html>",
    )
    assert find_main_product_image(BeautifulSoup(body, "html.parser"))[0] == PLACEHOLDER
