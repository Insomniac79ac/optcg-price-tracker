"""Offline tests for the authoritative Bandai release-name reference and the
generic release-text normalizer. No network.

Every "official" string below is Bandai's own, taken from the product pages
cited in release_reference.py. Every "observed" string is a real SNKRDUNK
release text retained by validation deployment 906a8b60 - used here as the
thing being CHECKED, never as the source of truth.
"""

import pytest

from snkrdunk_collector.identity import normalize_release_text, release_names_match
from snkrdunk_collector.release_reference import (
    MATCH_BANDAI_OFFICIAL,
    MATCH_SOURCE_RENDERING,
    RELEASE_NAME_AUTHORITY,
    RELEASE_REFERENCES,
    classify_release_name_match,
    get_release_reference,
)

# Exactly as retained from deployment 906a8b60.
OBSERVED = {
    "OP-01": "ブースターパック ロマンスドーン",
    "OP-02": "ブースターパック頂上決戦",
    "OP-03": "ブースターパック 強大な敵",
    "OP-04": "ブースターパック 謀略の王国",
}


class TestAuthoritativeTable:
    def test_all_four_current_releases_are_present(self):
        assert sorted(RELEASE_REFERENCES) == ["OP-01", "OP-02", "OP-03", "OP-04"]

    @pytest.mark.parametrize(
        "code,official",
        [
            ("OP-01", "ROMANCE DAWN"),
            ("OP-02", "頂上決戦"),
            ("OP-03", "強大な敵"),
            ("OP-04", "謀略の王国"),
        ],
    )
    def test_official_names_match_bandai_product_pages(self, code, official):
        assert get_release_reference(code).bandai_official_name == official

    def test_every_reference_cites_a_bandai_source_url(self):
        for ref in RELEASE_REFERENCES.values():
            assert ref.source_url.startswith("https://www.onepiece-cardgame.com/")

    def test_no_marketplace_rendering_is_recorded_as_a_bandai_name(self):
        """additional_official_names is for Bandai's own alternate renderings
        only. A storefront spelling belongs in snkrdunk_renderings, which is
        reported separately - never as a Bandai name."""
        for ref in RELEASE_REFERENCES.values():
            assert ref.additional_official_names == ()
            for rendering in ref.snkrdunk_renderings:
                assert rendering not in ref.bandai_names()

    def test_lookup_is_case_and_whitespace_insensitive(self):
        assert get_release_reference(" op-03 ").bandai_official_name == "強大な敵"

    def test_unknown_release_returns_none_rather_than_a_guess(self):
        assert get_release_reference("OP-99") is None
        assert get_release_reference(None) is None
        assert get_release_reference("") is None

    def test_authority_is_named_for_the_audit_record(self):
        assert RELEASE_NAME_AUTHORITY == "Bandai official Japanese product page"


class TestNormalization:
    @pytest.mark.parametrize(
        "observed,official",
        [
            ("ブースターパック ROMANCE DAWN", "ROMANCE DAWN"),
            ("ブースターパック頂上決戦", "頂上決戦"),
            ("ブースターパック 強大な敵", "強大な敵"),
            ("ブースターパック 謀略の王国", "謀略の王国"),
        ],
    )
    def test_category_prefix_is_stripped(self, observed, official):
        assert release_names_match(observed, official)

    @pytest.mark.parametrize(
        "variant",
        [
            "ブースターパック強大な敵",        # no space
            "ブースターパック 強大な敵",       # halfwidth space
            "ブースターパック　強大な敵",       # fullwidth space
            "  ブースターパック  強大な敵  ",   # padded
            "ブースターパック 強大な敵【OP-03】",  # product-code bracket
        ],
    )
    def test_spacing_and_bracket_variations_all_compare_equal(self, variant):
        assert release_names_match(variant, "強大な敵")

    def test_bare_official_name_without_any_prefix_matches(self):
        assert release_names_match("強大な敵", "強大な敵")

    def test_latin_name_is_case_insensitive(self):
        assert release_names_match("ブースターパック romance dawn", "ROMANCE DAWN")

    def test_unrelated_japanese_product_title_does_not_match(self):
        assert not release_names_match("ブースターパック 二つの伝説", "強大な敵")

    def test_different_release_names_never_collide(self):
        officials = [r.bandai_official_name for r in RELEASE_REFERENCES.values()]
        normalized = [normalize_release_text(n) for n in officials]
        assert len(set(normalized)) == len(officials)

    def test_prefix_only_text_normalizes_to_nothing_and_never_matches(self):
        assert normalize_release_text("ブースターパック") is None
        assert not release_names_match("ブースターパック", "強大な敵")

    def test_empty_and_none_never_match(self):
        assert not release_names_match(None, "強大な敵")
        assert not release_names_match("", "強大な敵")
        assert not release_names_match("強大な敵", None)

    def test_normalizer_does_not_transliterate(self):
        """The normalizer folds formatting only. Katakana must never be
        rewritten into Latin - only Bandai can attest a rendering."""
        assert normalize_release_text("ロマンスドーン") != normalize_release_text("ROMANCE DAWN")


class TestObservedSnkrdunkTextAgainstBandai:
    """The offline cross-check for the four releases currently in production."""

    @pytest.mark.parametrize("code", ["OP-02", "OP-03", "OP-04"])
    def test_natively_japanese_releases_match_bandai(self, code):
        ref = get_release_reference(code)
        assert release_names_match(OBSERVED[code], ref.bandai_official_name)

    def test_op01_observed_katakana_is_not_a_bandai_name_match(self):
        """Bandai titles OP-01 "ROMANCE DAWN" in Latin letters; SNKRDUNK (like
        Amazon.co.jp) transliterates it. The katakana must never satisfy the
        BANDAI side of the check - it is accepted only via the declared
        source rendering, and reported as such."""
        ref = get_release_reference("OP-01")
        assert ref.bandai_official_name == "ROMANCE DAWN"
        assert not any(release_names_match(OBSERVED["OP-01"], n) for n in ref.bandai_names())


class TestSourceSpecificRenderings:
    """SNKRDUNK's own spelling of a release is recorded as storefront
    nomenclature - accepted for matching, never presented as a Bandai name."""

    def test_op01_katakana_is_declared_as_a_snkrdunk_rendering_not_a_bandai_name(self):
        ref = get_release_reference("OP-01")
        assert ref.snkrdunk_renderings == ("ロマンスドーン",)
        assert "ロマンスドーン" not in ref.bandai_names()
        assert ref.bandai_official_name == "ROMANCE DAWN"

    def test_observed_op01_katakana_now_matches_via_the_source_rendering(self):
        ref = get_release_reference("OP-01")
        assert any(release_names_match(OBSERVED["OP-01"], n) for n in ref.accepted_names())

    def test_match_against_katakana_is_classified_as_a_source_rendering(self):
        ref = get_release_reference("OP-01")
        assert (
            classify_release_name_match(ref, OBSERVED["OP-01"], release_names_match)
            == MATCH_SOURCE_RENDERING
        )

    def test_match_against_the_latin_name_is_classified_as_bandai(self):
        ref = get_release_reference("OP-01")
        assert (
            classify_release_name_match(ref, "ブースターパック ROMANCE DAWN", release_names_match)
            == MATCH_BANDAI_OFFICIAL
        )

    def test_the_other_releases_declare_no_source_rendering(self):
        for code in ("OP-02", "OP-03", "OP-04"):
            assert get_release_reference(code).snkrdunk_renderings == ()

    def test_a_source_rendering_is_scoped_to_its_own_release(self):
        """Not a global alias pool: OP-01's rendering must not satisfy OP-04."""
        assert classify_release_name_match(
            get_release_reference("OP-04"), OBSERVED["OP-01"], release_names_match
        ) is None

    def test_unmatched_name_classifies_as_neither(self):
        assert classify_release_name_match(
            get_release_reference("OP-03"), "ブースターパック 二つの伝説", release_names_match
        ) is None
