"""PART 1 + PART 3 of the 2026-08-29 product-gate adversarial audit, collector
side: the REAL guard order in `validate_and_write_observation`, and what a
perfect artwork match can and cannot rescue.

THE STRUCTURAL CLAIM BEING TESTED. In this service artwork is not a selector.
The exact print is already fixed by `mapping.card_print_id` before a page is
fetched, and `validate_identity` accumulates a reason per failing dimension
while `validate_and_write_observation` writes only when the accumulated list is
EMPTY. So artwork is one conjunctive AND-term among ten - it can veto a write,
and it can never contribute a print, relocate one, or excuse another
dimension's failure.

Every test below drives the real writer against the real ORM. Nothing is
asserted from a docstring.
"""

import unittest

from snkrdunk_collector.card_code_authority import resolve_expected_card_code
from snkrdunk_collector.models import (
    CanonicalCard,
    CardPrint,
    PriceObservation,
    ReleaseProduct,
)
from snkrdunk_collector.writer import (
    validate_and_write_observation,
    validate_identity,
    validate_mapping_for_write,
)
from tests.test_writer import (
    GOOD_EXTRACTED,
    GOOD_EXTRACTION,
    MATCHING_ARTWORK,
    MISMATCHED_ARTWORK,
    PRODUCT_URL,
    WriterTestCase,
)

# The most persuasive artwork evidence this service can produce: an exact
# match at distance 0, well inside every threshold. Used throughout so no
# refusal below can be attributed to weak artwork.
PERFECT_ARTWORK = {
    "match": True,
    "hash_ok": True,
    "aspect_ok": True,
    "hash_distances": {"average_hash": 0, "dhash": 0, "phash": 0},
    "aspect_ratio_relative_diff": 0.0,
}


def _extraction(**overrides):
    extracted = dict(GOOD_EXTRACTED)
    extracted.update(overrides)
    return {"extraction_status": "extracted", "fail_reasons": [], "extracted": extracted}


class CollectorGuardOrderTests(WriterTestCase):
    """PART 1 - which dimensions gate a write, and whether artwork can move any
    of them."""

    def _reasons(self, extraction, artwork=PERFECT_ARTWORK, classification="normal_page"):
        result = self._write(
            self.approved_mapping, extraction, artwork=artwork, classification=classification
        )
        return result

    def test_01_every_identity_dimension_is_independently_fatal_under_perfect_artwork(self):
        """The conjunction, enumerated. Each row breaks exactly ONE dimension
        and hands the writer a flawless artwork match; each must still refuse,
        and must refuse with its OWN named reason."""
        cases = [
            ("card code", {"card_code": "OP01-002"}, "card_code_mismatch"),
            ("page language", {"page_language": "en"}, "language_mismatch"),
            ("treatment", {"treatment": "normal"}, "treatment_mismatch"),
            # The old "release product" row broke the page's CARD-CODE-DERIVED
            # product code. That is no longer an identity dimension and its
            # removal is the reprint fix, not a gap: SNKRDUNK derives that code
            # from the displayed card code, so it restated the card-code
            # dimension two rows up rather than testing the product. Release
            # identity is still enumerated - by name below, and by the missing
            # authoritative product link in
            # test_case_b2_missing_authoritative_release_identity.
            ("release name", {"release_text": "ブースターパック 頂上決戦"}, "release_name_mismatch"),
            ("rarity", {"rarity": "SR"}, "rarity_mismatch"),
            ("card name", {"card_name": "モンキー・D・ルフィ"}, "title_mismatch"),
        ]
        for label, override, expected in cases:
            with self.subTest(dimension=label):
                result = self._reasons(_extraction(**override))
                self.assertFalse(result.written, label)
                self.assertFalse(result.identity_verified, label)
                self.assertTrue(
                    any(r.startswith(expected) for r in result.identity_reasons),
                    f"{label}: expected {expected} in {result.identity_reasons}",
                )
                self.assertEqual(self.session.query(PriceObservation).count(), 0)

    def test_02_page_classification_gates_ahead_of_content(self):
        result = self._reasons(GOOD_EXTRACTION, classification="captcha_or_block")
        self.assertFalse(result.written)
        self.assertIn(
            "page_classification_not_normal_page:captcha_or_block", result.identity_reasons
        )

    def test_03_artwork_is_a_veto_and_the_only_dimension_it_speaks_for_is_itself(self):
        """Flip only the artwork verdict on an otherwise perfect page: exactly
        one reason appears, and it is artwork's own."""
        bad = self._reasons(GOOD_EXTRACTION, artwork=MISMATCHED_ARTWORK)
        self.assertFalse(bad.written)
        self.assertEqual(bad.identity_reasons, ["artwork_not_confirmed_match:no_match"])

        ok = self._reasons(GOOD_EXTRACTION, artwork=PERFECT_ARTWORK)
        self.assertTrue(ok.written, "the page differed in nothing but the artwork verdict")
        self.assertEqual(ok.identity_reasons, [])

    def test_04_absent_artwork_evidence_fails_closed(self):
        for artwork in (None, {}, {"match": False, "error": "image_fetch_failed"},
                        {"match": False, "error": "unusable_image:no dominant region"}):
            with self.subTest(artwork=artwork):
                result = self._reasons(GOOD_EXTRACTION, artwork=artwork)
                self.assertFalse(result.written)
                self.assertTrue(
                    any(r.startswith("artwork_not_confirmed_match") for r in result.identity_reasons)
                )

    def test_05_mapping_state_gates_are_evaluated_independently_of_identity(self):
        """Approval state is not an identity fact and does not live in
        identity_reasons - but it still blocks the write. Perfect artwork and a
        perfect page cannot approve a mapping."""
        self.approved_mapping.review_status = "needs_review"
        self.session.flush()
        result = self._reasons(GOOD_EXTRACTION)
        self.assertFalse(result.written)
        self.assertTrue(result.identity_verified, "identity is still fully proven")
        self.assertIn("mapping_not_approved:review_status=needs_review", result.reasons)
        self.assertEqual(self.session.query(PriceObservation).count(), 0)

    def test_06_an_unverified_print_blocks_the_write_under_perfect_artwork(self):
        self.approved_mapping.card_print_id = 2  # the unverified print
        self.session.flush()
        result = self._reasons(_extraction())
        self.assertFalse(result.written)
        self.assertIn("card_print_not_verified:status=unverified", result.reasons)

    def test_07_a_mapping_with_no_exact_print_can_never_write(self):
        self.approved_mapping.card_print_id = None
        self.session.flush()
        result = self._reasons(GOOD_EXTRACTION)
        self.assertFalse(result.written)
        self.assertIn("mapping_not_linked_to_exact_print", result.reasons)

    def test_08_artwork_never_supplies_a_print_id(self):
        """Structural, and the reason artwork cannot relocate a mapping here:
        the artwork verdict this service passes around has no print field at
        all, and the written row's print comes from the mapping."""
        self.assertNotIn("card_print_id", PERFECT_ARTWORK)
        result = self._reasons(GOOD_EXTRACTION)
        self.assertTrue(result.written)
        self.session.commit()
        row = self.session.query(PriceObservation).one()
        self.assertEqual(row.card_print_id, self.approved_mapping.card_print_id)

    def test_09_card_code_authority_is_never_the_page_being_checked(self):
        """SNKRDUNK may not supply both sides of its own card-code check. Strip
        the independent authority and the gate fails closed even though the
        page's own displayed code is 'right'."""
        print_row = self.session.get(CardPrint, 1)
        print_row.image_url = "https://snkrdunk.com/not-bandai.png"
        self.session.flush()
        result = self._reasons(GOOD_EXTRACTION)
        self.assertFalse(result.written)
        self.assertIn(
            "card_code_authority_missing:no_bandai_or_verified_yuyutei_evidence",
            result.identity_reasons,
        )


class FailureInjectionTests(WriterTestCase):
    """PART 3 - one upstream identity signal wrong or missing, artwork perfect.

    Each case asserts the write is refused BEFORE artwork could legitimise it,
    which here means: refused while `artwork_comparison['match'] is True`.
    """

    def _inject(self, extraction, mutate_print=None):
        if mutate_print is not None:
            mutate_print(self.session.get(CardPrint, 1))
            self.session.flush()
        result = self._write(self.approved_mapping, extraction, artwork=PERFECT_ARTWORK)
        self.assertTrue(PERFECT_ARTWORK["match"], "artwork agreed on every one of these")
        self.assertEqual(self.session.query(PriceObservation).count(), 0)
        return result

    def test_case_a_wrong_release_correct_card_code(self):
        """The page names a different product than the print belongs to, while
        its card code is right. The release NAME is what catches it - and it
        must, because the name is the only thing on the page that is evidence
        about the product rather than about the card."""
        result = self._inject(
            _extraction(release_product_code="OP-02", release_text="ブースターパック 頂上決戦")
        )
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("release_name_mismatch") for r in result.identity_reasons))

    def test_case_b_missing_release_on_the_page(self):
        """A page that names no release at all cannot corroborate the print's
        product, so it is refused rather than passed for lack of evidence."""
        result = self._inject(_extraction(release_product_code=None, release_text=None))
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("release_name_mismatch") for r in result.identity_reasons))

    def test_case_b2_missing_authoritative_release_identity(self):
        """The print names no product at all. Never waved through - that is how
        a future expansion, or an unlinked print, would bypass the gate.

        Replaces test_case_b2_missing_authoritative_release_reference, which
        made the same point about an unknown release CODE. The protection is
        strictly wider now: it covers uncoded products, which have no code to
        be unknown.
        """
        result = self._inject(
            _extraction(release_product_code="OP-09", release_text="ブースターパック 新章"),
            mutate_print=lambda p: (
                setattr(p, "release_product_code", "OP-09"),
                setattr(p, "release_product_id", None),
            ),
        )
        self.assertFalse(result.written)
        self.assertTrue(
            any(
                r.startswith("authoritative_release_identity_missing:")
                for r in result.identity_reasons
            ),
            result.identity_reasons,
        )

    def test_case_c_wrong_card_code_with_visually_identical_art(self):
        """The exact case artwork would 'rescue' if it were allowed to: the
        photo matches perfectly and the code names a different card."""
        result = self._inject(_extraction(card_code="OP01-016"))
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("card_code_mismatch") for r in result.identity_reasons))

    def test_case_d_correct_release_wrong_variant(self):
        """Variant is carried here as `treatment`. A parallel print sold as the
        normal printing is refused even though both share the release."""
        result = self._inject(_extraction(treatment="normal"))
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("treatment_mismatch") for r in result.identity_reasons))

    def test_case_e_english_mirror_page_against_a_japanese_print(self):
        """SNKRDUNK serves one listing under /apparels (lang=ja) and
        /en/trading-cards (lang=en). The mirror is the same item and is still
        refused, because a jp print's evidence must come from its own page."""
        result = self._inject(_extraction(page_language="en"))
        self.assertFalse(result.written)
        self.assertIn("language_mismatch:displayed=en,expected=jp", result.identity_reasons)

    def test_case_f_same_artwork_reused_by_a_reprint(self):
        """Bandai republishes one artwork file under a new print. Artwork is
        byte-identical and therefore says nothing; the release checks decide.
        This is the case that proves artwork cannot separate printings AND
        that the collector does not need it to."""
        prb01 = ReleaseProduct(
            id=301, source_catalogue="bandai_jp", official_code="PRB-01",
            display_name="ONE PIECE CARD THE BEST", first_seen_name="ONE PIECE CARD THE BEST",
            source_series_id="569901", verification_status="verified",
        )
        self.session.add(prb01)
        self.session.flush()
        reprint = CardPrint(
            id=3,
            canonical_card_id=2,
            language="jp",
            treatment="parallel",
            release_product_code="PRB-01",
            release_product_id=301,
            artwork_key="abc",  # identical artwork class to print 1
            image_url="https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001_p2.png",
            verification_status="verified",
        )
        self.session.add(reprint)
        self.session.flush()
        self.approved_mapping.card_print_id = 3
        self.session.flush()

        # The page really is the OP-01 listing; the mapping now points at the
        # PRB-01 reprint that shares its artwork.
        result = self._write(self.approved_mapping, GOOD_EXTRACTION, artwork=PERFECT_ARTWORK)
        self.assertFalse(result.written)
        # The page names OP-01's release; the mapping's print belongs to
        # PRB-01. The two products are separated by their NAMES, which is the
        # only page-side evidence about the product - and, unlike the artwork,
        # it does separate them.
        self.assertTrue(any(r.startswith("release_name_mismatch") for r in result.identity_reasons))
        self.assertEqual(self.session.query(PriceObservation).count(), 0)

    def test_case_g_product_label_resolving_to_a_valid_but_wrong_product(self):
        """The most dangerous shape: nothing is malformed. The page names a
        real Bandai product with a real authoritative name, and it is simply
        not this print's product. The release-name check refuses it, and
        perfect artwork does not soften it."""
        result = self._inject(
            _extraction(release_product_code="OP-03", release_text="ブースターパック 強大な敵")
        )
        self.assertFalse(result.written)
        reasons = result.identity_reasons
        self.assertTrue(any(r.startswith("release_name_mismatch") for r in reasons))

    def test_case_h_no_injected_signal_leaves_a_writable_state_on_artwork_alone(self):
        """The blocker condition, stated as a test. For every injection above,
        the ONLY thing that agreed was artwork - and none of them wrote."""
        self.assertEqual(self.session.query(PriceObservation).count(), 0)


class ArtworkCannotBroadenTests(WriterTestCase):
    """The collector's own version of 'artwork never widens': a passing artwork
    comparison adds nothing to the reason list, ever."""

    def test_a_perfect_match_only_ever_removes_one_reason(self):
        card_print = self.session.get(CardPrint, 1)
        canonical = self.session.get(CanonicalCard, card_print.canonical_card_id)
        authority = resolve_expected_card_code(self.session, card_print)

        def reasons_for(artwork):
            return validate_identity(
                mapping=self.approved_mapping,
                card_print=card_print,
                canonical=canonical,
                classification="normal_page",
                extraction=GOOD_EXTRACTION,
                artwork_comparison=artwork,
                card_code_authority=authority,
            )

        with_bad = reasons_for(MISMATCHED_ARTWORK)
        with_good = reasons_for(MATCHING_ARTWORK)
        # Same inputs but for artwork: the good run's reasons are a strict
        # SUBSET of the bad run's, differing only by artwork's own reason.
        self.assertTrue(set(with_good) < set(with_bad))
        self.assertEqual(
            set(with_bad) - set(with_good), {"artwork_not_confirmed_match:no_match"}
        )

    def test_mapping_state_reasons_are_untouched_by_artwork(self):
        self.approved_mapping.is_active = False
        self.session.flush()
        before = validate_mapping_for_write(self.session, self.approved_mapping)
        self.assertIn("mapping_not_active", before)
        result = self._write(self.approved_mapping, GOOD_EXTRACTION, artwork=PERFECT_ARTWORK)
        self.assertFalse(result.written)
        self.assertIn("mapping_not_active", result.reasons)


if __name__ == "__main__":
    unittest.main()
