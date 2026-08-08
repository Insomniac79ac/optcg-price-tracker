"""Tests for yuyutei_collector.writer against an in-memory SQLite database
using the collector's own minimal ORM models (models.py) - no network, no
staging database. Covers the fail-closed gates required before this
tranche's real observation could be written to staging.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from yuyutei_collector.db import Base
from yuyutei_collector.models import Card, CardPrint, PriceObservation, Source, SourceCardMapping
from yuyutei_collector.writer import validate_and_write_observation

PRODUCT_URL = "https://yuyu-tei.jp/sell/opc/card/op01/10002"

GOOD_EXTRACTION = {
    "extraction_status": "extracted",
    "fail_reasons": [],
    "extracted": {
        "card_code": "OP01-001",
        "treatment": "parallel",
        "sell_price_jpy": 34800,
        "stock_status": "out_of_stock",
    },
}

FAIL_CLOSED_EXTRACTION = {
    "extraction_status": "fail_closed",
    "fail_reasons": ["price_disagreement:jsonld=34800,dom=39800"],
    "extracted": {
        "card_code": "OP01-001",
        "treatment": "parallel",
        "sell_price_jpy": None,
        "stock_status": "out_of_stock",
    },
}


class WriterTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine, future=True)
        self.session = Session()

        card = Card(id=11, card_code="OP01-001", name_en="Roronoa Zoro (Parallel)")
        source = Source(id=1, name="yuyutei", base_url="https://yuyu-tei.jp")
        self.session.add_all([card, source])
        self.session.flush()

        self.verified_print = CardPrint(
            id=1, canonical_card_id=2, treatment="parallel", verification_status="verified"
        )
        self.unverified_print = CardPrint(
            id=2, canonical_card_id=2, treatment="parallel", verification_status="unverified"
        )
        self.session.add_all([self.verified_print, self.unverified_print])
        self.session.flush()

        self.approved_mapping = SourceCardMapping(
            id=11, card_id=11, source_id=1, card_print_id=1,
            source_card_id="OP01-001", source_url=PRODUCT_URL,
            is_active=True, review_status="approved",
        )
        self.session.add(self.approved_mapping)
        self.session.flush()

    def tearDown(self):
        self.session.close()

    def _write(self, mapping, extraction, html="<html>evidence</html>"):
        return validate_and_write_observation(
            session=self.session,
            mapping=mapping,
            classification="normal_product",
            extraction=extraction,
            http_status=200,
            raw_html=html,
            source_url=PRODUCT_URL,
            parser_version="yuyutei-collector-v3",
        )


class SuccessfulWriteTests(WriterTestCase):
    def test_successful_extraction_writes_one_observation(self):
        result = self._write(self.approved_mapping, GOOD_EXTRACTION)
        self.assertTrue(result.written)
        self.session.commit()
        self.assertEqual(self.session.query(PriceObservation).count(), 1)

    def test_observation_receives_all_four_lineage_identifiers(self):
        result = self._write(self.approved_mapping, GOOD_EXTRACTION)
        self.assertTrue(result.written)
        self.assertEqual(result.card_id, 11)
        self.assertEqual(result.card_print_id, 1)
        self.assertEqual(result.source_id, 1)
        self.assertEqual(result.source_card_mapping_id, 11)

    def test_duplicate_run_creates_a_new_observation_not_a_mutation(self):
        first = self._write(self.approved_mapping, GOOD_EXTRACTION)
        self.session.commit()
        second = self._write(self.approved_mapping, GOOD_EXTRACTION)
        self.session.commit()
        self.assertTrue(first.written and second.written)
        self.assertNotEqual(first.observation_id, second.observation_id)
        self.assertEqual(self.session.query(PriceObservation).count(), 2)
        # The first row must be untouched - same id, still queryable.
        still_there = self.session.get(PriceObservation, first.observation_id)
        self.assertIsNotNone(still_there)
        self.assertEqual(still_there.price_jpy, 34800)


class FailClosedWriteTests(WriterTestCase):
    def test_failed_extraction_writes_zero_observation_rows(self):
        result = self._write(self.approved_mapping, FAIL_CLOSED_EXTRACTION)
        self.assertFalse(result.written)
        self.assertIn("price_disagreement:jsonld=34800,dom=39800", result.reasons)
        self.session.rollback()
        self.assertEqual(self.session.query(PriceObservation).count(), 0)

    def test_code_mismatch_vs_mapping_fails_closed(self):
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

    def test_mapping_not_linked_to_exact_print_is_rejected(self):
        unlinked = SourceCardMapping(
            id=12, card_id=11, source_id=1, card_print_id=None,
            source_card_id="OP01-001", source_url=PRODUCT_URL + "-other",
            is_active=True, review_status="approved",
        )
        self.session.add(unlinked)
        self.session.flush()
        result = self._write(unlinked, GOOD_EXTRACTION)
        self.assertFalse(result.written)
        self.assertIn("mapping_not_linked_to_exact_print", result.reasons)
        self.assertEqual(self.session.query(PriceObservation).count(), 0)

    def test_mock_or_demo_unverified_print_is_never_treated_as_verified(self):
        # A mapping pointing at an unverified print - exactly the shape a
        # careless seed/demo linkage would have - must fail closed even
        # though every other field would otherwise validate cleanly.
        demo_mapping = SourceCardMapping(
            id=13, card_id=11, source_id=1, card_print_id=2,  # unverified_print
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
        result = validate_and_write_observation(
            session=self.session,
            mapping=self.approved_mapping,
            classification="challenge_or_captcha",
            extraction=GOOD_EXTRACTION,
            http_status=200,
            raw_html="<html>challenge</html>",
            source_url=PRODUCT_URL,
            parser_version="yuyutei-collector-v3",
        )
        self.assertFalse(result.written)
        self.assertTrue(any(r.startswith("page_classification_not_normal_product:") for r in result.reasons))

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
