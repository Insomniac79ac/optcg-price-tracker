"""Tests for snkrdunk_collector.writer against an in-memory SQLite database
using the collector's own minimal ORM models (models.py) - no network, no
staging database. Covers every fail-closed gate required before a real
observation can be written (mirrors
services/yuyutei_collector/tests/test_writer.py's structure)."""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from snkrdunk_collector.db import Base
from snkrdunk_collector.models import (
    CanonicalCard,
    Card,
    CardPrint,
    PriceObservation,
    Source,
    SourceCardMapping,
)
from snkrdunk_collector.release_reference import MATCH_BANDAI_OFFICIAL, MATCH_SOURCE_RENDERING
from snkrdunk_collector.writer import validate_and_write_observation

PRODUCT_URL = "https://snkrdunk.com/apparels/104428"
PARSER_VERSION = "snkrdunk-collector-v2"

GOOD_EXTRACTED = {
    "card_name": "ロロノア・ゾロ",
    "card_code": "OP01-001",
    "rarity": "L",
    "treatment": "parallel",
    "page_language": "ja",
    # Bandai titles OP-01 in Latin letters; see release_reference.py. A page
    # showing the katakana transliteration fails the name gate on purpose -
    # covered by test_release_reference.py and the mismatch test below.
    "release_text": "ブースターパック ROMANCE DAWN",
    "release_product_code": "OP-01",
    "raw_floor_jpy": 24500,
    "raw_floor_condition": "B",
}

GOOD_EXTRACTION = {
    "extraction_status": "extracted",
    "fail_reasons": [],
    "extracted": GOOD_EXTRACTED,
}

FAIL_CLOSED_EXTRACTION = {
    "extraction_status": "fail_closed",
    "fail_reasons": ["no_raw_condition_price_available"],
    "extracted": dict(GOOD_EXTRACTED, raw_floor_jpy=None, raw_floor_condition=None),
}

MATCHING_ARTWORK = {"match": True, "hash_distances": {"average_hash": 3}}
MISMATCHED_ARTWORK = {"match": False, "hash_distances": {"average_hash": 40}}


class WriterTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine, future=True)
        self.session = Session()

        card = Card(id=11, card_code="OP01-001", name_en="Roronoa Zoro (Parallel)")
        source = Source(id=2, name="snkrdunk", base_url="https://snkrdunk.com")
        # The print's canonical identity is the verification authority for
        # name/rarity/set - deliberately NOT cards.*, whose rarity column
        # carries display variants rather than the real rarity token.
        canonical = CanonicalCard(
            id=2,
            card_code="OP01-001",
            name_en="Roronoa Zoro",
            name_jp="ロロノア・ゾロ",
            rarity="L",
            original_set_code="OP-01",
        )
        self.session.add_all([card, source, canonical])
        self.session.flush()

        self.verified_print = CardPrint(
            id=1,
            canonical_card_id=2,
            language="jp",
            treatment="parallel",
            release_product_code="OP-01",
            artwork_key="abc",
            image_url="https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001_p2.png",
            verification_status="verified",
        )
        self.unverified_print = CardPrint(
            id=2,
            canonical_card_id=2,
            language="jp",
            treatment="parallel",
            release_product_code="OP-01",
            verification_status="unverified",
        )
        self.session.add_all([self.verified_print, self.unverified_print])
        self.session.flush()

        self.approved_mapping = SourceCardMapping(
            id=35,
            card_id=11,
            source_id=2,
            card_print_id=1,
            source_card_id="OP01-001",
            source_url=PRODUCT_URL,
            is_active=True,
            review_status="approved",
        )
        self.session.add(self.approved_mapping)
        self.session.flush()

    def tearDown(self):
        self.session.close()

    def _write(self, mapping, extraction, artwork=MATCHING_ARTWORK, html="<html>evidence</html>", classification="normal_page"):
        return validate_and_write_observation(
            session=self.session,
            mapping=mapping,
            classification=classification,
            extraction=extraction,
            artwork_comparison=artwork,
            http_status=200,
            raw_html=html,
            source_url=PRODUCT_URL,
            parser_version=PARSER_VERSION,
        )


class SuccessfulWriteTests(WriterTestCase):
    def test_one_successful_run_writes_exactly_one_floor_observation(self):
        result = self._write(self.approved_mapping, GOOD_EXTRACTION)
        self.assertTrue(result.written)
        self.session.commit()
        self.assertEqual(self.session.query(PriceObservation).count(), 1)
        row = self.session.query(PriceObservation).one()
        self.assertEqual(row.price_type, "floor")
        self.assertEqual(row.price_jpy, 24500)
        self.assertEqual(row.condition_label, "B")

    def test_observation_receives_all_lineage_identifiers(self):
        result = self._write(self.approved_mapping, GOOD_EXTRACTION)
        self.assertTrue(result.written)
        self.assertEqual(result.card_id, 11)
        self.assertEqual(result.card_print_id, 1)
        self.assertEqual(result.source_id, 2)
        self.assertEqual(result.source_card_mapping_id, 35)

    def test_rerunning_later_creates_a_new_observation_not_a_mutation(self):
        first = self._write(self.approved_mapping, GOOD_EXTRACTION)
        self.session.commit()
        second = self._write(self.approved_mapping, GOOD_EXTRACTION)
        self.session.commit()
        self.assertTrue(first.written and second.written)
        self.assertNotEqual(first.observation_id, second.observation_id)
        self.assertEqual(self.session.query(PriceObservation).count(), 2)
        still_there = self.session.get(PriceObservation, first.observation_id)
        self.assertIsNotNone(still_there)
        self.assertEqual(still_there.price_jpy, 24500)


class FailClosedWriteTests(WriterTestCase):
    def test_no_raw_price_writes_zero_observation_rows(self):
        result = self._write(self.approved_mapping, FAIL_CLOSED_EXTRACTION)
        self.assertFalse(result.written)
        self.assertIn("no_raw_condition_price_available", result.reasons)
        self.session.rollback()
        self.assertEqual(self.session.query(PriceObservation).count(), 0)

    def test_artwork_mismatch_fails_closed(self):
        result = self._write(self.approved_mapping, GOOD_EXTRACTION, artwork=MISMATCHED_ARTWORK)
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("artwork_not_confirmed_match") for r in result.reasons))
        self.assertEqual(self.session.query(PriceObservation).count(), 0)

    def test_missing_artwork_comparison_fails_closed(self):
        result = self._write(self.approved_mapping, GOOD_EXTRACTION, artwork=None)
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("artwork_not_confirmed_match") for r in result.reasons))

    def test_card_code_mismatch_fails_closed(self):
        extraction = dict(GOOD_EXTRACTION, extracted=dict(GOOD_EXTRACTED, card_code="OP01-099"))
        result = self._write(self.approved_mapping, extraction)
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("card_code_mismatch:") for r in result.reasons))
        self.assertFalse(result.identity_verified)
        self.assertEqual(self.session.query(PriceObservation).count(), 0)

    def test_treatment_mismatch_fails_closed(self):
        extraction = dict(GOOD_EXTRACTION, extracted=dict(GOOD_EXTRACTED, treatment="normal"))
        result = self._write(self.approved_mapping, extraction)
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("treatment_mismatch:") for r in result.reasons))
        self.assertFalse(result.identity_verified)

    def test_language_mismatch_fails_closed(self):
        """A foreign-language (e.g. /en/) variant page must never be
        accepted as evidence for a jp-language card_print."""
        extraction = dict(GOOD_EXTRACTION, extracted=dict(GOOD_EXTRACTED, page_language="en"))
        result = self._write(self.approved_mapping, extraction)
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("language_mismatch:") for r in result.reasons))
        self.assertFalse(result.identity_verified)

    def test_release_product_mismatch_fails_closed(self):
        """A product whose own card code belongs to a different set than the
        linked print must never be accepted."""
        extraction = dict(
            GOOD_EXTRACTION,
            extracted=dict(GOOD_EXTRACTED, release_product_code="OP-04", card_code="OP01-001"),
        )
        result = self._write(self.approved_mapping, extraction)
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("release_product_mismatch:") for r in result.reasons))
        self.assertFalse(result.identity_verified)

    def test_release_product_mismatch_reason_retains_observed_release_text(self):
        extraction = dict(
            GOOD_EXTRACTION,
            extracted=dict(GOOD_EXTRACTED, release_product_code="OP-04", release_text="別のブースター"),
        )
        result = self._write(self.approved_mapping, extraction)
        reason = next(r for r in result.reasons if r.startswith("release_product_mismatch:"))
        self.assertIn("release_text=別のブースター", reason)

    def test_release_name_mismatch_is_its_own_reason(self):
        """A product whose card code says OP-01 but whose release name is a
        different Bandai product - a reprint or alternate product carrying an
        unchanged code. release_product_mismatch alone cannot see this."""
        extraction = dict(
            GOOD_EXTRACTION,
            extracted=dict(GOOD_EXTRACTED, release_text="ブースターパック 強大な敵"),
        )
        result = self._write(self.approved_mapping, extraction)
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("release_name_mismatch:") for r in result.reasons))
        # The code-level check still agrees, proving the two are independent.
        self.assertFalse(any(r.startswith("release_product_mismatch:") for r in result.reasons))
        self.assertFalse(result.identity_verified)

    def test_release_name_mismatch_reason_names_its_authority(self):
        extraction = dict(
            GOOD_EXTRACTION,
            extracted=dict(GOOD_EXTRACTED, release_text="ブースターパック 謀略の王国"),
        )
        result = self._write(self.approved_mapping, extraction)
        reason = next(r for r in result.reasons if r.startswith("release_name_mismatch:"))
        self.assertIn("expected=ROMANCE DAWN", reason)
        self.assertIn("authority=Bandai official Japanese product page", reason)

    def test_correct_release_name_with_wrong_code_is_a_code_mismatch(self):
        extraction = dict(GOOD_EXTRACTION, extracted=dict(GOOD_EXTRACTED, release_product_code="OP-04"))
        result = self._write(self.approved_mapping, extraction)
        self.assertTrue(any(r.startswith("release_product_mismatch:") for r in result.reasons))
        self.assertFalse(any(r.startswith("release_name_mismatch:") for r in result.reasons))

    def test_snkrdunk_katakana_op01_rendering_passes_as_source_nomenclature(self):
        """The real observed OP-01 text. Accepted via the declared SNKRDUNK
        rendering - but the record must say it matched storefront
        nomenclature, NOT a Bandai official name."""
        extraction = dict(
            GOOD_EXTRACTION,
            extracted=dict(GOOD_EXTRACTED, release_text="ブースターパック ロマンスドーン"),
        )
        result = self._write(self.approved_mapping, extraction)
        self.assertTrue(result.identity_verified, result.identity_reasons)
        self.assertEqual(result.release_name_match_authority, MATCH_SOURCE_RENDERING)
        self.assertNotEqual(result.release_name_match_authority, MATCH_BANDAI_OFFICIAL)

    def test_bandai_latin_op01_rendering_is_reported_as_bandai(self):
        result = self._write(self.approved_mapping, GOOD_EXTRACTION)
        self.assertTrue(result.identity_verified)
        self.assertEqual(result.release_name_match_authority, MATCH_BANDAI_OFFICIAL)

    def test_a_source_rendering_never_widens_to_another_release(self):
        """snkrdunk_renderings is scoped to its own release, not a global
        alias pool - OP-01's rendering must not satisfy OP-04."""
        self.verified_print.release_product_code = "OP-04"
        self.session.flush()
        extraction = dict(
            GOOD_EXTRACTION,
            extracted=dict(
                GOOD_EXTRACTED,
                release_product_code="OP-04",
                release_text="ブースターパック ロマンスドーン",
            ),
        )
        result = self._write(self.approved_mapping, extraction)
        self.assertFalse(result.identity_verified)
        self.assertTrue(any(r.startswith("release_name_mismatch:") for r in result.reasons))

    def test_missing_release_text_fails_closed(self):
        extraction = dict(GOOD_EXTRACTION, extracted=dict(GOOD_EXTRACTED, release_text=None))
        result = self._write(self.approved_mapping, extraction)
        self.assertFalse(result.identity_verified)
        self.assertTrue(any(r.startswith("release_name_mismatch:") for r in result.reasons))

    def test_unknown_release_fails_closed_rather_than_skipping_the_check(self):
        """An OP05+ expansion must not bypass the gate by simply having no
        reference entry."""
        future_print = CardPrint(
            id=5, canonical_card_id=2, language="jp", treatment="parallel",
            release_product_code="OP-99", verification_status="verified",
            image_url="https://example.invalid/x.png",
        )
        self.session.add(future_print)
        self.session.flush()
        future_mapping = SourceCardMapping(
            id=95, card_id=11, source_id=2, card_print_id=5,
            source_card_id="OP99-001", source_url=PRODUCT_URL + "-future",
            is_active=True, review_status="approved",
        )
        self.session.add(future_mapping)
        self.session.flush()
        extraction = dict(
            GOOD_EXTRACTION,
            extracted=dict(
                GOOD_EXTRACTED,
                card_code="OP99-001",
                release_product_code="OP-99",
                release_text="ブースターパック 未知の製品",
            ),
        )
        result = self._write(future_mapping, extraction)
        self.assertFalse(result.written)
        self.assertFalse(result.identity_verified)
        self.assertTrue(
            any(r.startswith("authoritative_release_name_missing:") for r in result.identity_reasons)
        )
        self.assertEqual(self.session.query(PriceObservation).count(), 0)

    def test_rarity_mismatch_fails_closed(self):
        extraction = dict(GOOD_EXTRACTION, extracted=dict(GOOD_EXTRACTED, rarity="SR"))
        result = self._write(self.approved_mapping, extraction)
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("rarity_mismatch:") for r in result.reasons))
        self.assertFalse(result.identity_verified)

    def test_title_mismatch_fails_closed(self):
        extraction = dict(GOOD_EXTRACTION, extracted=dict(GOOD_EXTRACTED, card_name="ナミ"))
        result = self._write(self.approved_mapping, extraction)
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("title_mismatch:") for r in result.reasons))
        self.assertFalse(result.identity_verified)

    def test_title_tolerates_extra_source_formatting_around_the_name(self):
        """SNKRDUNK appending legitimate formatting must not fail identity -
        the expected name still appears whole."""
        extraction = dict(GOOD_EXTRACTION, extracted=dict(GOOD_EXTRACTED, card_name="ロロノア・ゾロ 【美品】"))
        result = self._write(self.approved_mapping, extraction)
        self.assertTrue(result.identity_verified, result.reasons)
        self.assertTrue(result.written)

    def test_title_missing_name_fails_closed(self):
        extraction = dict(GOOD_EXTRACTION, extracted=dict(GOOD_EXTRACTED, card_name=None))
        result = self._write(self.approved_mapping, extraction)
        self.assertFalse(result.identity_verified)
        self.assertTrue(any(r.startswith("title_mismatch:") for r in result.reasons))

    def test_mapping_not_linked_to_exact_print_is_rejected(self):
        unlinked = SourceCardMapping(
            id=36, card_id=11, source_id=2, card_print_id=None,
            source_card_id="OP01-001", source_url=PRODUCT_URL + "-other",
            is_active=True, review_status="approved",
        )
        self.session.add(unlinked)
        self.session.flush()
        result = self._write(unlinked, GOOD_EXTRACTION)
        self.assertFalse(result.written)
        self.assertIn("mapping_not_linked_to_exact_print", result.reasons)
        self.assertEqual(self.session.query(PriceObservation).count(), 0)

    def test_unverified_print_is_never_treated_as_verified(self):
        demo_mapping = SourceCardMapping(
            id=37, card_id=11, source_id=2, card_print_id=2,  # unverified_print
            source_card_id="OP01-001", source_url=PRODUCT_URL + "-demo",
            is_active=True, review_status="approved",
        )
        self.session.add(demo_mapping)
        self.session.flush()
        result = self._write(demo_mapping, GOOD_EXTRACTION)
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("card_print_not_verified:") for r in result.reasons))
        self.assertEqual(self.session.query(PriceObservation).count(), 0)

    def test_non_normal_classification_fails_closed(self):
        result = self._write(self.approved_mapping, GOOD_EXTRACTION, classification="challenge_or_captcha")
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("page_classification_not_normal_page:") for r in result.reasons))

    def test_inactive_mapping_is_rejected(self):
        self.approved_mapping.is_active = False
        self.session.flush()
        result = self._write(self.approved_mapping, GOOD_EXTRACTION)
        self.assertFalse(result.written)
        self.assertIn("mapping_not_active", result.reasons)

    def test_needs_review_mapping_is_rejected(self):
        self.approved_mapping.review_status = "needs_review"
        self.session.flush()
        result = self._write(self.approved_mapping, GOOD_EXTRACTION)
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("mapping_not_approved:") for r in result.reasons))


class IdentityVersusPriceTests(WriterTestCase):
    """Identity and price availability are separate verdicts - a print with
    no listed A-D price is still fully identifiable (PASS_FLOOR_UNAVAILABLE)."""

    def test_floor_unavailable_does_not_fail_identity(self):
        result = self._write(self.approved_mapping, FAIL_CLOSED_EXTRACTION)
        self.assertTrue(result.identity_verified, result.identity_reasons)
        self.assertEqual(result.identity_reasons, [])
        # It still blocks the write, because a write needs a price.
        self.assertFalse(result.written)
        self.assertIn("no_raw_condition_price_available", result.reasons)

    def test_floor_unavailable_still_reports_observed_price_as_none(self):
        result = self._write(self.approved_mapping, FAIL_CLOSED_EXTRACTION)
        self.assertIsNone(result.price_jpy)

    def test_unwritten_result_still_reports_the_observed_floor(self):
        """A validate-only run needs the real observed floor to tell PASS
        from PASS_FLOOR_UNAVAILABLE, even though nothing is written."""
        self.approved_mapping.review_status = "needs_review"
        self.session.flush()
        result = self._write(self.approved_mapping, GOOD_EXTRACTION)
        self.assertFalse(result.written)
        self.assertTrue(result.identity_verified, result.identity_reasons)
        self.assertEqual(result.price_jpy, 24500)
        self.assertEqual(result.condition_label, "B")

    def test_unapproved_mapping_does_not_taint_identity_verdict(self):
        """review_status is an approval gate, never an identity signal."""
        self.approved_mapping.review_status = "needs_review"
        self.session.flush()
        result = self._write(self.approved_mapping, GOOD_EXTRACTION)
        self.assertTrue(result.identity_verified)
        self.assertNotIn(
            "mapping_not_approved:review_status=needs_review", result.identity_reasons
        )
        self.assertIn("mapping_not_approved:review_status=needs_review", result.reasons)

    def test_identity_fails_when_canonical_card_is_missing(self):
        orphan_print = CardPrint(
            id=9, canonical_card_id=999, language="jp", treatment="parallel",
            release_product_code="OP-01", verification_status="verified",
        )
        self.session.add(orphan_print)
        self.session.flush()
        orphan_mapping = SourceCardMapping(
            id=90, card_id=11, source_id=2, card_print_id=9,
            source_card_id="OP01-001", source_url=PRODUCT_URL + "-orphan",
            is_active=True, review_status="approved",
        )
        self.session.add(orphan_mapping)
        self.session.flush()
        result = self._write(orphan_mapping, GOOD_EXTRACTION)
        self.assertFalse(result.identity_verified)
        self.assertIn("canonical_card_missing_for_identity_check", result.identity_reasons)

    def test_all_identity_dimensions_pass_on_a_genuine_match(self):
        result = self._write(self.approved_mapping, GOOD_EXTRACTION)
        self.assertTrue(result.identity_verified)
        self.assertEqual(result.identity_reasons, [])
        self.assertTrue(result.written)


class RarityAuthorityTests(WriterTestCase):
    """Which column supplies the rarity this check compares against.

    The Bandai catalogue import (4D-8) landed 20 canonical cards - 66 prints -
    whose card-level rarity is intentionally NULL because the catalogue
    publishes several rarities for that card code, while each print's own
    entry publishes exactly one. Comparing against the card-level column
    rejected those prints for a fact Atlas holds about them.

    Every test below mutates only the two rarity columns on the fixture print,
    so each one isolates the rarity dimension while every other identity gate
    stays exactly as the passing fixture leaves it.
    """

    def _set_rarities(self, *, canonical, official):
        self.session.query(CanonicalCard).filter_by(id=2).one().rarity = canonical
        self.verified_print.official_rarity = official
        self.session.flush()

    def test_print_official_rarity_is_accepted_when_canonical_is_null(self):
        """The 4D-9 case. Previously rejected as rarity_mismatch:expected=None."""
        self._set_rarities(canonical=None, official="L")

        result = self._write(self.approved_mapping, GOOD_EXTRACTION)

        self.assertTrue(result.identity_verified)
        self.assertFalse(any(r.startswith("rarity_mismatch:") for r in result.reasons))
        self.assertTrue(result.written)

    def test_print_official_rarity_still_rejects_a_disagreeing_page(self):
        """Falling back is not relaxing: a wrong rarity is still a mismatch."""
        self._set_rarities(canonical=None, official="L")
        extraction = dict(GOOD_EXTRACTION, extracted=dict(GOOD_EXTRACTED, rarity="SR"))

        result = self._write(self.approved_mapping, extraction)

        self.assertFalse(result.written)
        self.assertFalse(result.identity_verified)
        self.assertTrue(any(r.startswith("rarity_mismatch:") for r in result.reasons))

    def test_no_trustworthy_rarity_anywhere_fails_closed(self):
        """Neither column holds a value, so there is nothing to agree with -
        and the page's own claim must never stand in for one."""
        self._set_rarities(canonical=None, official=None)

        result = self._write(self.approved_mapping, GOOD_EXTRACTION)

        self.assertFalse(result.written)
        self.assertFalse(result.identity_verified)
        self.assertIn(
            "rarity_mismatch:displayed=L,expected=None", result.identity_reasons
        )
        self.assertEqual(self.session.query(PriceObservation).count(), 0)

    def test_the_prints_own_rarity_outranks_the_card_level_summary(self):
        """Rarity belongs to the printing: where the two disagree, the print's
        catalogue entry is the one describing this exact product."""
        self._set_rarities(canonical="SR", official="L")

        result = self._write(self.approved_mapping, GOOD_EXTRACTION)

        self.assertTrue(result.identity_verified)
        self.assertTrue(result.written)

    def test_canonical_rarity_still_governs_a_print_without_its_own(self):
        """Every mapping that predates the import keeps behaving identically:
        those prints carry no official_rarity and their card-level value is
        still what a page is checked against."""
        self._set_rarities(canonical="L", official=None)

        self.assertTrue(self._write(self.approved_mapping, GOOD_EXTRACTION).written)

        self._set_rarities(canonical="L", official=None)
        extraction = dict(GOOD_EXTRACTION, extracted=dict(GOOD_EXTRACTED, rarity="SR"))
        mismatched = self._write(self.approved_mapping, extraction)
        self.assertFalse(mismatched.written)
        self.assertTrue(
            any(r.startswith("rarity_mismatch:") for r in mismatched.reasons)
        )

    def test_a_blank_official_rarity_falls_back_rather_than_failing(self):
        self._set_rarities(canonical="L", official="   ")

        self.assertTrue(self._write(self.approved_mapping, GOOD_EXTRACTION).written)

    def test_rarity_check_writes_nothing_when_it_refuses(self):
        """The refusal path is still zero rows, not a row marked bad."""
        self._set_rarities(canonical=None, official="SEC")

        result = self._write(self.approved_mapping, GOOD_EXTRACTION)

        self.assertFalse(result.written)
        self.session.commit()
        self.assertEqual(self.session.query(PriceObservation).count(), 0)


if __name__ == "__main__":
    unittest.main()


# --- the four mappings released from quarantine on 2026-08-29 ----------------
#
# Blinded human review (sealed key sha-256 2e51968a...9eb145) confirmed all four
# point at the printing they already named. They were moved needs_review ->
# approved. Two of them STILL do not price, and that is the intended end state:
# the artwork gate is unchanged, and 42 and 43 sit outside it. These tests pin
# that "approved" and "priceable" are different things, using each mapping's own
# measured collector distance under the shared subject-isolation crop.
QUARANTINE_RELEASE_2026_08_29 = {
    42: {"average_hash": 13, "aspect": 0.0012, "gate": False},
    43: {"average_hash": 19, "aspect": 0.0012, "gate": False},
    49: {"average_hash": 11, "aspect": 0.0094, "gate": True},
    52: {"average_hash": 12, "aspect": 0.0012, "gate": True},
}


def _measured_artwork(mapping_id: int) -> dict:
    c = QUARANTINE_RELEASE_2026_08_29[mapping_id]
    return {
        "match": c["gate"],
        "hash_distances": {"average_hash": c["average_hash"]},
        "aspect_ratio_relative_diff": c["aspect"],
    }


class QuarantineReleaseTests(WriterTestCase):
    """What the four released mappings do when a collection actually runs."""

    def test_approved_but_refused_by_artwork_writes_nothing_and_says_why(self):
        """Mappings 42 and 43. Approving them removed the approval reason and
        nothing else; the artwork gate is untouched and still refuses, so no
        price is written and the run reports exactly one cause."""
        for mapping_id in (42, 43):
            with self.subTest(mapping=mapping_id):
                result = self._write(
                    self.approved_mapping, GOOD_EXTRACTION, artwork=_measured_artwork(mapping_id)
                )
                self.assertFalse(result.written)
                self.assertTrue(
                    any(r.startswith("artwork_not_confirmed_match") for r in result.reasons)
                )
                # The point of the state change: approval is no longer a reason.
                self.assertFalse(
                    any(r.startswith("mapping_not_approved") for r in result.reasons)
                )
        # A refused write returns before anything is added, so the table is
        # still empty without needing a rollback to prove it.
        self.assertEqual(self.session.query(PriceObservation).count(), 0)

    def test_approved_and_accepted_by_the_unchanged_gate_writes_normally(self):
        """Mappings 49 and 52. 52 already passed the gate; 49 passes now only
        because the crop stopped spanning a second object on its canvas. Neither
        needed a threshold to move."""
        for mapping_id in (49, 52):
            with self.subTest(mapping=mapping_id):
                result = self._write(
                    self.approved_mapping, GOOD_EXTRACTION, artwork=_measured_artwork(mapping_id)
                )
                self.assertTrue(result.written, result.reasons)
                self.assertEqual(result.reasons, [])
        self.assertEqual(self.session.query(PriceObservation).count(), 2)

    def test_before_the_release_approval_was_also_blocking(self):
        """The state these four were actually in. Reproduced so the change is
        legible: `needs_review` blocked the write on its own, independently of
        artwork, which is why 52 was unpriced despite passing the gate."""
        self.approved_mapping.review_status = "needs_review"
        self.session.flush()
        result = self._write(self.approved_mapping, GOOD_EXTRACTION, artwork=_measured_artwork(52))
        self.assertFalse(result.written)
        self.assertIn("mapping_not_approved:review_status=needs_review", result.reasons)
        self.assertFalse(
            any(r.startswith("artwork_not_confirmed_match") for r in result.reasons)
        )
