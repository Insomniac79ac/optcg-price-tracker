"""Rarity as EVIDENCE, and the three silences that are not the same silence.

WHY THIS FILE EXISTS. Nine of the thirty approved canary mappings failed
`rarity_mismatch` on 2026-08-31 with `displayed=None` - every one of them
because the collector read no rarity from the title at all. Diagnosing them
against the English mirror of the very same listings (whose
`snkrdunk_candidates.detected_rarity` Atlas had already parsed) split them into
three classes that must NOT be treated alike:

  1. PARSER GAP (3).  "ジンベエ C パラレル [ST01-005]". The rarity is right
     there; `パラレル` is the Japanese for `Parallel`, the prose form of the
     "-P" suffix this parser already understood. Atlas's own discovery parser
     reads the English "C Parallel" as rarity C - so recognising the katakana
     makes the collector agree with a reading Atlas had already committed to.

  2. UNREADABLE CLAIM (2).  "モンキー・D・ルフィ：手配書 SR-SPC [ST01-012]".
     A compound of a base rarity and a special-print category. Decoding it
     would mean equating SNKRDUNK's "SPC" with Bandai's "SPカード", and no such
     attestation exists. STILL REFUSED, deliberately.

  3. NO RARITY PUBLISHED (4).  "ナミ [ST01-007]". SNKRDUNK prints no rarity for
     these listings - confirmed on BOTH language pages, where Atlas's own
     discovery parser also stored an empty detected_rarity. Absent evidence
     narrows nothing.

The whole point of the change is that (2) and (3) look identical downstream -
both yield `rarity=None` - and must reach opposite verdicts.
"""

import unittest

from snkrdunk_collector.identity import (
    RARITY_ABSENT,
    RARITY_PUBLISHED,
    RARITY_UNRECOGNISED,
    parse_card_identity,
)
from snkrdunk_collector.models import CanonicalCard, ReleaseProduct
from tests.test_writer import (
    GOOD_EXTRACTED,
    GOOD_EXTRACTION,
    WriterTestCase,
)


class RarityParsingTests(unittest.TestCase):
    """Class boundaries, at the parser."""

    def test_class_1_katakana_parallel_yields_the_rarity_before_it(self):
        for title, rarity, name in [
            ("ジンベエ C パラレル  [ST01-005] (X)", "C", "ジンベエ"),
            ("イゾウ UC パラレル [OP01-033] (X)", "UC", "イゾウ"),
            ("ブラックマリア C パラレル [ST04-011] (X)", "C", "ブラックマリア"),
        ]:
            with self.subTest(title=title):
                r = parse_card_identity(title)
                self.assertEqual(r["rarity"], rarity)
                self.assertEqual(r["treatment"], "parallel")
                self.assertEqual(r["name"], name)
                self.assertEqual(r["rarity_evidence"], RARITY_PUBLISHED)

    def test_the_english_prose_form_reads_identically(self):
        """The same listing on the English mirror. Same structure, same
        answer - which is the evidence that the katakana reading is right."""
        r = parse_card_identity("Jimbe C Parallel [ST01-005] (X)")
        self.assertEqual((r["rarity"], r["treatment"], r["name"]), ("C", "parallel", "Jimbe"))

    def test_class_2_a_compound_rarity_token_is_unrecognised_not_absent(self):
        """SR-SPC must be distinguishable from silence, or it would be waved
        through by the absent-rarity rule."""
        for title in [
            "モンキー・D・ルフィ：手配書 SR-SPC [ST01-012](X)",
            "トラファルガー・ロー SR-SPC [OP01-047] (X)",
        ]:
            with self.subTest(title=title):
                r = parse_card_identity(title)
                self.assertIsNone(r["rarity"])
                self.assertEqual(r["rarity_evidence"], RARITY_UNRECOGNISED)

    def test_class_3_a_title_with_no_rarity_field_is_absent(self):
        for title, name in [
            ("ブエナ・フェスタ [ST05-014] (X)", "ブエナ・フェスタ"),
            ("ナミ [ST01-007]  (X)", "ナミ"),
            ("ジュエリー・ボニー [ST02-007]  (X)", "ジュエリー・ボニー"),
            ("戦桃丸 [ST03-007]  (X)", "戦桃丸"),
        ]:
            with self.subTest(title=title):
                r = parse_card_identity(title)
                self.assertIsNone(r["rarity"])
                self.assertEqual(r["name"], name)
                self.assertEqual(r["rarity_evidence"], RARITY_ABSENT)

    def test_the_existing_dash_p_and_bare_forms_are_untouched(self):
        r = parse_card_identity("ニコ・ロビン C-P  [ST01-008] (X)")
        self.assertEqual((r["rarity"], r["treatment"]), ("C", "parallel"))
        self.assertEqual(r["rarity_evidence"], RARITY_PUBLISHED)
        r = parse_card_identity("サンジ R [OP01-013] (X)")
        self.assertEqual((r["rarity"], r["treatment"]), ("R", "normal"))
        self.assertEqual(r["rarity_evidence"], RARITY_PUBLISHED)

    def test_a_treatment_word_is_only_consumed_when_a_rarity_precedes_it(self):
        """A card whose NAME ends in the word must not lose a token. Nothing
        rarity-shaped precedes it, so the title parses exactly as before."""
        r = parse_card_identity("ミラー パラレル [OP01-001] (X)")
        self.assertIsNone(r["rarity"])
        self.assertEqual(r["name"], "ミラー パラレル")
        self.assertEqual(r["rarity_evidence"], RARITY_ABSENT)


class RarityGateTests(WriterTestCase):
    """The verdicts, end to end through validate_and_write_observation."""

    def _extraction(self, **over):
        return dict(GOOD_EXTRACTION, extracted=dict(GOOD_EXTRACTED, **over))

    def test_a_published_rarity_that_matches_still_passes(self):
        result = self._write(self.approved_mapping, self._extraction())
        self.assertTrue(result.identity_verified, result.identity_reasons)

    def test_a_published_rarity_that_differs_still_fails_closed(self):
        """THE CHECK THAT MUST NOT WEAKEN. A genuinely wrong rarity is still
        refused - this is the case the whole gate exists for."""
        result = self._write(self.approved_mapping, self._extraction(rarity="SEC"))
        self.assertFalse(result.identity_verified)
        self.assertTrue(any(r.startswith("rarity_mismatch") for r in result.reasons))
        self.assertFalse(result.written)

    def test_an_unrecognised_rarity_token_fails_closed(self):
        """Class 2. `rarity=None` but the title made a claim we cannot read -
        it must NOT be treated as silence."""
        result = self._write(
            self.approved_mapping,
            self._extraction(rarity=None, rarity_evidence=RARITY_UNRECOGNISED),
        )
        self.assertFalse(result.identity_verified)
        reason = next(r for r in result.reasons if r.startswith("rarity_mismatch"))
        self.assertIn("evidence=unrecognised", reason)
        self.assertFalse(result.written)

    def test_an_absent_rarity_contributes_no_evidence_and_does_not_refuse(self):
        """Class 3. The listing publishes no rarity, so the dimension is
        silent - every OTHER dimension still had to pass to get here."""
        result = self._write(
            self.approved_mapping,
            self._extraction(rarity=None, rarity_evidence=RARITY_ABSENT),
        )
        self.assertTrue(result.identity_verified, result.identity_reasons)
        self.assertFalse(any(r.startswith("rarity_mismatch") for r in result.reasons))

    def test_a_missing_evidence_field_defaults_to_the_strict_behaviour(self):
        """FAIL-CLOSED DEFAULT. Any caller that does not supply
        `rarity_evidence` - an older extraction record, a future code path -
        gets the pre-change verdict: a null rarity is a mismatch. The new
        leniency is opt-in and only the parser can grant it."""
        extraction = self._extraction(rarity=None)
        extraction["extracted"].pop("rarity_evidence", None)
        result = self._write(self.approved_mapping, extraction)
        self.assertFalse(result.identity_verified)
        self.assertTrue(any(r.startswith("rarity_mismatch") for r in result.reasons))

    def test_absent_rarity_does_not_rescue_any_other_dimension(self):
        """Silence on rarity is not silence on everything: a wrong card code
        alongside an absent rarity is still refused."""
        result = self._write(
            self.approved_mapping,
            self._extraction(
                card_code="OP01-002", rarity=None, rarity_evidence=RARITY_ABSENT
            ),
        )
        self.assertFalse(result.identity_verified)
        self.assertTrue(any(r.startswith("card_code_mismatch") for r in result.reasons))

    def test_an_absent_rarity_still_fails_when_atlas_holds_no_rarity_either(self):
        """Unchanged rule: an absent EXPECTED value is a mismatch, never a
        pass. A catalogue gap cannot corroborate anything, and the listing
        being silent too does not make two unknowns agree."""
        self.verified_print.official_rarity = None
        self.session.get(CanonicalCard, 2).rarity = None
        self.session.flush()
        result = self._write(
            self.approved_mapping,
            self._extraction(rarity=None, rarity_evidence=RARITY_ABSENT),
        )
        self.assertFalse(result.identity_verified)
        self.assertTrue(any(r.startswith("rarity_mismatch") for r in result.reasons))

    def test_base_and_parallel_are_still_separated_by_the_other_dimensions(self):
        """An absent rarity must not blur base vs parallel. Treatment is
        checked independently whenever Atlas classifies the print."""
        self.verified_print.treatment = "parallel"
        self.session.flush()
        result = self._write(
            self.approved_mapping,
            self._extraction(
                treatment="normal", rarity=None, rarity_evidence=RARITY_ABSENT
            ),
        )
        self.assertFalse(result.identity_verified)
        self.assertTrue(any(r.startswith("treatment_mismatch") for r in result.reasons))

    def test_a_reprint_in_another_product_is_still_separated(self):
        """Rarity silence does not let a reprint pass as its original: the
        release name is checked against the print's own ReleaseProduct."""
        op03 = ReleaseProduct(
            id=903, source_catalogue="bandai_jp", official_code="OP-03",
            display_name="強大な敵", first_seen_name="強大な敵",
            source_series_id="569003", verification_status="verified",
        )
        self.session.add(op03)
        self.verified_print.release_product_code = "OP-03"
        self.verified_print.release_product_id = 903
        self.session.flush()
        result = self._write(
            self.approved_mapping,
            self._extraction(rarity=None, rarity_evidence=RARITY_ABSENT),
        )
        self.assertFalse(result.identity_verified)
        self.assertTrue(any(r.startswith("release_name_mismatch") for r in result.reasons))


if __name__ == "__main__":
    unittest.main()
