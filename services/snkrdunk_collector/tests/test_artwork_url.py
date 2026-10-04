import pytest

from snkrdunk_collector.artwork_url import artwork_url

PRODUCT = "https://snkrdunk.com/apparels/104428"


@pytest.mark.parametrize("value,expected,error", [
    ("https://cdn.snkrdunk.com/card.jpg", "https://cdn.snkrdunk.com/card.jpg", None),
    ("/images/products/104428.jpg", "https://snkrdunk.com/images/products/104428.jpg", None),
    ("/_next/static/media/no-image.a123.webp", None, "placeholder_image_url"),
    ("https://snkrdunk.com/_next/static/media/no-image.a123.webp", None, "placeholder_image_url"),
    (None, None, "missing_image_url"),
    ("", None, "missing_image_url"),
    ("//other.test/card.jpg", None, "invalid_image_url"),
    ("javascript:alert(1)", None, "invalid_image_url"),
    ("relative.jpg", None, "invalid_image_url"),
])
def test_artwork_locator(value, expected, error):
    assert artwork_url(value, PRODUCT) == (expected, error)


def test_relative_asset_needs_canonical_product_origin():
    assert artwork_url("/image.jpg", "https://other.test/apparels/104428") == (None, "invalid_image_url")
