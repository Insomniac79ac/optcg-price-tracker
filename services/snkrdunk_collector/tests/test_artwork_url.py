import pytest
from snkrdunk_collector.artwork_url import artwork_url


def test_root_relative_artwork_uses_the_verified_product_origin():
    assert artwork_url('/images/card.png', 'https://snkrdunk.com/apparels/123') == ('https://snkrdunk.com/images/card.png', None)


@pytest.mark.parametrize('value', [None, '', '/images/no_image.png', '/placeholder.jpg', 'images/card.png', 'http://example.test/card.png', 'https://user:password@example.test/card.png', '//example.test/card.png'])
def test_missing_placeholder_or_unsafe_locator_never_becomes_artwork_evidence(value):
    url, reason = artwork_url(value, 'https://snkrdunk.com/apparels/123')
    assert url is None and reason is not None


def test_relative_locator_requires_a_canonical_product_identity():
    assert artwork_url('/images/card.png', 'https://snkrdunk.com/search')[0] is None
