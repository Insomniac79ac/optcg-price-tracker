"""Tests for snkrdunk_collector.writer against an in-memory SQLite database
using the collector's own minimal ORM models (models.py) - no network, no
staging database. Covers every fail-closed gate required before a real
observation can be written (mirrors
services/yuyutei_collector/tests/test_writer.py's structure)."""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from snkrdunk_collector.db import Base
from snkrdunk_collector.models import Card, CardPrint, PriceObservation, Source, SourceCardMapping
from snkrdunk_collector.writer import validate_and_write_observation

PRODUCT_URL = "https://snkrdunk.com/apparels/104428"
PARSER_VERSION = "snkrdunk-collector-v1"

GOOD_EXTRACTION = {
    "extraction_status": "extracted",
    "fail_reasons": [],
    "extracted": {
        "card_code": "OP01-001",
        "treatment": "parallel",
        "page_language": "ja",
        "raw_floor_jpy": 24500,
        "raw_floor_condition": "B",
    },
}

FAIL_CLOSED_EXTRACTION = {
    "extraction_status": "fail_closed",
    "fail_reasons": ["no_raw_condition_price_available"],
    "extracted": {
        "card_code": "OP01-001",
        "treatment": "parallel",
        "page_language": "ja",
        "raw_floor_jpy": None,
        "raw_floor_condition": None,
    },
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
        self.session.add_all([card, source])
        self.session.flush()

        self.verified_print = CardPrint(
            id=1,
            canonical_card_id=2,
            language="jp",
            treatment="parallel",
            artwork_key="abc",
            image_url="https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001_p2.png",
            verification_status="verified",
        )
        self.unverified_print = CardPrint(
            id=2,
            canonical_card_id=2,
            language="jp",
            treatment="parallel",
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

    def test_card_code_mismatch_vs_mapping_fails_closed(self):
        extraction = dict(GOOD_EXTRACTION, extracted=dict(GOOD_EXTRACTION["extracted"], card_code="OP01-099"))
        result = self._write(self.approved_mapping, extraction)
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("card_code_mismatch_vs_mapping:") for r in result.reasons))
        self.assertEqual(self.session.query(PriceObservation).count(), 0)

    def test_treatment_mismatch_vs_print_fails_closed(self):
        extraction = dict(GOOD_EXTRACTION, extracted=dict(GOOD_EXTRACTION["extracted"], treatment="normal"))
        result = self._write(self.approved_mapping, extraction)
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("treatment_mismatch_vs_print:") for r in result.reasons))

    def test_language_mismatch_vs_print_fails_closed(self):
        """A foreign-language (e.g. /en/) variant page must never be
        accepted as evidence for a jp-language card_print."""
        extraction = dict(GOOD_EXTRACTION, extracted=dict(GOOD_EXTRACTION["extracted"], page_language="en"))
        result = self._write(self.approved_mapping, extraction)
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("language_mismatch_vs_print:") for r in result.reasons))

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


if __name__ == "__main__":
    unittest.main()
