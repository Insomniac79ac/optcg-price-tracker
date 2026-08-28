"""The canonical SNKRDUNK listing URL contract (4F-9).

SNKRDUNK serves one listing under two paths - `/apparels/{id}` (lang="ja")
and `/en/trading-cards/{id}` (lang="en"). Discovery walks the English
sitemap; the collector rejects a page whose language disagrees with the
print's. So an approval must store the path matching the PRINT's language,
not the path discovery happened to see, or the mapping is approved and
permanently unpriceable - which is exactly what staging mappings 75/76 were.
"""

import pytest

from app.services.exact_print_approval import (
    REFUSAL_SOURCE_URL_NOT_CANONICAL,
    ExactPrintApprovalError,
)
from app.services.snkrdunk_urls import (
    canonical_listing_url,
    equivalent_listing_urls,
    listing_id,
)

EN = "https://snkrdunk.com/en/trading-cards/171994"
JP = "https://snkrdunk.com/apparels/171994"


# --- listing identity --------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        EN,
        JP,
        EN + "?slide=right&query_id=bdee3ab0-067a-44e9-9419-98014106449c",
        JP + "/sales-histories",
    ],
)
def test_both_paths_and_their_suffixes_resolve_to_one_listing_id(url):
    assert listing_id(url) == "171994"


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "https://snkrdunk.com/cards/OP01-001",
        "https://snkrdunk.com/apparels/not-a-number",
        "https://example.com/apparels/171994",
        "http://snkrdunk.com/apparels/171994",
        "https://evil.test/https://snkrdunk.com/apparels/171994",
    ],
)
def test_unrecognised_urls_have_no_listing_id(url):
    assert listing_id(url) is None


# --- canonicalisation --------------------------------------------------------


def test_en_url_canonicalises_to_the_jp_page_for_a_jp_print():
    """The whole point: a jp print must be collected from the Japanese page."""
    assert canonical_listing_url(EN, card_print_language="jp") == JP


def test_already_canonical_jp_url_is_unchanged():
    assert canonical_listing_url(JP, card_print_language="jp") == JP


def test_en_print_canonicalises_to_the_english_page():
    """Language drives the path, not a blanket rewrite to /apparels."""
    assert canonical_listing_url(JP, card_print_language="en") == EN
    assert canonical_listing_url(EN, card_print_language="en") == EN


@pytest.mark.parametrize("language", ["jp", "JP", " jp "])
def test_language_is_matched_case_and_whitespace_insensitively(language):
    assert canonical_listing_url(EN, card_print_language=language) == JP


@pytest.mark.parametrize(
    "url",
    ["https://snkrdunk.com/cards/OP01-001", "https://example.com/apparels/1", None],
)
def test_unrecognised_url_refuses_rather_than_being_rewritten(url):
    with pytest.raises(ExactPrintApprovalError) as exc:
        canonical_listing_url(url, card_print_language="jp")
    assert exc.value.code == REFUSAL_SOURCE_URL_NOT_CANONICAL


@pytest.mark.parametrize("language", [None, "", "fr", "ja"])
def test_unknown_print_language_refuses(language):
    """'ja' is the HTML lang, not a card_print.language - accepting it would
    silently mean 'jp' and hide a real data problem."""
    with pytest.raises(ExactPrintApprovalError) as exc:
        canonical_listing_url(EN, card_print_language=language)
    assert exc.value.code == REFUSAL_SOURCE_URL_NOT_CANONICAL


def test_the_refusal_is_a_client_error_not_a_review_queue_item():
    exc = ExactPrintApprovalError(REFUSAL_SOURCE_URL_NOT_CANONICAL, "x")
    assert exc.needs_review is False


# --- matching a candidate to its mapping across the boundary -----------------


@pytest.mark.parametrize("url", [EN, JP])
def test_equivalent_urls_cover_both_paths_from_either_side(url):
    assert set(equivalent_listing_urls(url)) == {EN, JP}


def test_equivalent_urls_are_exact_strings_not_patterns():
    """Nothing here may become a LIKE/regex against stored URLs."""
    for value in equivalent_listing_urls(EN):
        assert "%" not in value and "*" not in value


def test_equivalent_urls_of_an_unrecognised_url_are_empty():
    assert equivalent_listing_urls("https://snkrdunk.com/cards/OP01-001") == ()
