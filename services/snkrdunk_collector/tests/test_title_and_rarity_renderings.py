"""Two storefront-spelling equivalences, and the differences that stay refused.

Both were exposed by the 50-mapping batch of 2026-08-31 (mappings 107-156) and
both are declared from OBSERVED evidence, never from resemblance:

  * `title_mismatch` on 113 and 117 - SNKRDUNK served `ケイミ―` and `カル―` with
    U+2015 HORIZONTAL BAR where Bandai publishes U+30FC, the Japanese
    prolonged sound mark. The names were otherwise character-for-character
    identical.
  * `rarity_mismatch evidence=unrecognised` on 130-136 (and 88, 91 earlier) -
    the compound token `SR-SPC`.

The tests that matter most here are the NEGATIVE ones. A normalisation is only
as good as what it still refuses, so each accepted equivalence is paired with
the nearest difference that must not be swallowed.
"""

import unittest

from snkrdunk_collector.identity import normalize_card_name, parse_card_identity
from snkrdunk_collector.models import CanonicalCard
from snkrdunk_collector.source_rarity_renderings import (
    SOURCE_RARITY_RENDERINGS,
    rendering_for_token,
)
from tests.test_writer import GOOD_EXTRACTED, GOOD_EXTRACTION, WriterTestCase


class ProlongedSoundMarkTests(unittest.TestCase):
    """U+2015 restored to U+30FC, but only where it is doing that job."""

    def test_the_two_observed_names_become_equal(self):
        for displayed, expected in [("ケイミ―", "ケイミー"), ("カル―", "カルー")]:
            with self.subTest(name=expected):
                self.assertEqual(normalize_card_name(displayed), normalize_card_name(expected))

    def test_mapping_154_shaped_difference_is_still_refused(self):
        """The wave-dash COUNT differs (four versus three). That is a different
        name, not a different spelling of the same one - and no amount of
        character folding may equate them."""
        displayed = "ラディカルビ〜〜〜〜ム!!!!"
        expected = "ラディカルビ～～～ム‼‼"
        self.assertNotEqual(normalize_card_name(displayed), normalize_card_name(expected))

    def test_154_differs_on_two_independent_axes_not_just_count(self):
        """Records exactly WHY 154 refuses, because the reason is not the one
        it first appears to be.

        Two independent differences, either of which alone is enough:
          1. the dash COUNT - four U+301C against three U+FF5E;
          2. the dash CHARACTER CLASS - NFKC folds U+FF5E to ASCII `~` but
             leaves U+301C WAVE DASH untouched, so they do not converge even
             at equal counts.

        Only the exclamation halves agree (NFKC decomposes U+203C to `!!`).
        Nothing in this tranche normalises either axis, and neither should be
        normalised without its own observed evidence.
        """
        three_each = normalize_card_name("ラディカルビ〜〜〜ム!!!!")
        bandai = normalize_card_name("ラディカルビ～～～ム‼‼")
        self.assertNotEqual(three_each, bandai, "count is not the only difference")
        self.assertIn("〜", three_each)
        self.assertIn("~", bandai)
        # The exclamation marks DO converge, which is why the dashes are the
        # whole story.
        self.assertTrue(three_each.endswith("!!!!") and bandai.endswith("!!!!"))

    def test_a_dash_not_following_kana_is_left_alone(self):
        """The context test. Between Latin letters, digits, or at the start of
        a string, U+2015 is an ordinary dash and must not be rewritten -
        otherwise this becomes punctuation-collapsing."""
        for text in ["A―B", "1―2", "―ナミ", "ABC―DEF"]:
            with self.subTest(text=text):
                self.assertIn("―", normalize_card_name(text))

    def test_two_genuinely_different_names_are_not_equated(self):
        self.assertNotEqual(normalize_card_name("ケイミー"), normalize_card_name("カルー"))
        self.assertNotEqual(normalize_card_name("ナミ"), normalize_card_name("ナミー"))

    def test_normalisation_never_changes_length(self):
        """One codepoint in, one out - a structural guard against this ever
        growing into stripping."""
        for text in ["ケイミ―", "カル―", "A―B", "ラディカルビ〜〜〜〜ム"]:
            with self.subTest(text=text):
                self.assertEqual(len(normalize_card_name(text)), len(text))


class SourceRarityRenderingTests(unittest.TestCase):
    """The declared table, and the tokens deliberately absent from it."""

    def test_sr_spc_is_declared_with_both_halves_and_evidence(self):
        row = rendering_for_token("snkrdunk", "SR-SPC")
        self.assertIsNotNone(row)
        self.assertEqual(row.base_rarity, "SR")
        self.assertEqual(row.print_rarity, "SPカード")
        self.assertEqual(len(row.observed_card_codes), 9)
        self.assertIn("counterexample", row.evidence)

    def test_the_related_but_unverified_tokens_are_not_declared(self):
        """`SR-SP` and `SEC-SP` exist in the corpus but have no approved
        mapping, so no verified print backs them. They must keep failing."""
        for token in ["SR-SP", "SEC-SP", "SPC", "SP", "sr-spc", "SR-SPCX", "SR_SPC", ""]:
            with self.subTest(token=token):
                self.assertIsNone(rendering_for_token("snkrdunk", token))

    def test_a_rendering_is_scoped_to_its_source(self):
        self.assertIsNone(rendering_for_token("yuyutei", "SR-SPC"))

    def test_the_table_stays_small_and_evidenced(self):
        for row in SOURCE_RARITY_RENDERINGS:
            with self.subTest(token=row.source_token):
                self.assertTrue(row.observed_card_codes)
                self.assertGreater(len(row.evidence), 120)

    def test_the_token_is_surfaced_by_the_parser(self):
        r = parse_card_identity("モンキー・D・ルフィ：手配書 SR-SPC [ST01-012](X)")
        self.assertEqual(r["rarity_token"], "SR-SPC")
        self.assertEqual(r["rarity_evidence"], "unrecognised")
        self.assertIsNone(r["rarity"])

    def test_a_readable_rarity_never_carries_a_token(self):
        """A declared rendering must never get the chance to override a rarity
        that WAS read."""
        for title in ["サンジ R [OP01-013] (X)", "ニコ・ロビン C-P [ST01-008] (X)", "ナミ [ST01-007] (X)"]:
            with self.subTest(title=title):
                self.assertIsNone(parse_card_identity(title)["rarity_token"])


class SrSpcGateTests(WriterTestCase):
    """End to end: both halves are verified, and either one disagreeing refuses."""

    def _spc(self, **over):
        base = dict(
            GOOD_EXTRACTED, rarity=None, rarity_evidence="unrecognised",
            rarity_token="SR-SPC",
        )
        base.update(over)
        return dict(GOOD_EXTRACTION, extracted=base)

    def _atlas(self, print_rarity, canonical_rarity):
        self.verified_print.official_rarity = print_rarity
        self.session.get(CanonicalCard, 2).rarity = canonical_rarity
        self.session.flush()

    def test_sr_spc_passes_when_atlas_agrees_on_both_halves(self):
        self._atlas("SPカード", "SR")
        result = self._write(self.approved_mapping, self._spc())
        self.assertTrue(result.identity_verified, result.identity_reasons)

    def test_it_refuses_when_the_print_rarity_is_not_sp(self):
        """The dangerous case a single-value alias would wave through: the
        title says SP, the printing is an ordinary SR."""
        self._atlas("SR", "SR")
        result = self._write(self.approved_mapping, self._spc())
        self.assertFalse(result.identity_verified)
        self.assertTrue(
            any(r.startswith("rarity_rendering_contradicted") for r in result.reasons),
            result.reasons,
        )

    def test_it_refuses_when_the_base_rarity_is_not_sr(self):
        """The second half. `SR-SPC` asserts an SR card; a C card wearing that
        token is a contradiction even though its print IS an SP printing."""
        self._atlas("SPカード", "C")
        result = self._write(self.approved_mapping, self._spc())
        self.assertFalse(result.identity_verified)
        self.assertTrue(any(r.startswith("rarity_rendering_contradicted") for r in result.reasons))

    def test_an_undeclared_compound_token_still_fails_closed(self):
        """`SR-SP` is not declared, so it takes the unchanged unrecognised
        path - no rendering, no acceptance."""
        self._atlas("SPカード", "SR")
        result = self._write(self.approved_mapping, self._spc(rarity_token="SR-SP"))
        self.assertFalse(result.identity_verified)
        self.assertTrue(any(r.startswith("rarity_mismatch") for r in result.reasons))
        self.assertIn("evidence=unrecognised", next(
            r for r in result.reasons if r.startswith("rarity_mismatch")
        ))

    def test_an_ordinary_wrong_rarity_is_untouched_by_any_of_this(self):
        result = self._write(
            self.approved_mapping,
            dict(GOOD_EXTRACTION, extracted=dict(GOOD_EXTRACTED, rarity="SEC")),
        )
        self.assertFalse(result.identity_verified)
        self.assertTrue(any(r.startswith("rarity_mismatch") for r in result.reasons))


if __name__ == "__main__":
    unittest.main()
