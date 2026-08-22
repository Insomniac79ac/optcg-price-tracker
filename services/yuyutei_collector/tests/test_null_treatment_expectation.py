"""A CardPrint whose treatment is NULL has no Atlas classification, so the
collector must have NO treatment expectation for it - it must not fail the
page closed just because the page shows one.

NULL means "Atlas has not classified this print", never "the source must
return NULL". Getting this wrong would silently stop every unclassified print
from being priced, which is the failure this file exists to prevent.

Mismatch detection for a non-null treatment is unchanged, and every case
proving that is exercised here beside the null ones."""

import unittest

from yuyutei_collector.extractor import EXPECTED_TREATMENT, extract_with_agreement

PRODUCT_URL = "https://yuyu-tei.jp/sell/opc/card/op01/10002"


def _product_html(card_code: str = "OP01-002", marker: str = "", price: str = "500") -> str:
    """`marker` is the treatment word Yuyu-Tei puts in the title: パラレル for
    a parallel product, ノーマル for an explicitly-normal one, and nothing at
    all for the base printing (which the extractor resolves to "normal")."""
    title = f"トラファルガー・ロー {marker}".strip()
    return (
        "<html><head>"
        '<script type="application/ld+json">{"@context":"http://schema.org","@type":"Product",'
        f'"name":"{title}",'
        f'"description":"{card_code}",'
        f'"offers":{{"@type":"Offer","price":"{price}","priceCurrency":"JPY","availability":"InStock"}}}}'
        "</script></head><body>"
        f'<div class="power" id="power"><h3>{title}</h3></div>'
        '<section id="product-detail">'
        f'<span class="pote">{card_code}</span>'
        f"<h4> {price} 円</h4>"
        "<label> 在庫 :   ○   </label>"
        "</section></body></html>"
    )


def _untitled_html(card_code: str = "OP01-002", price: str = "500") -> str:
    """No title anywhere, which is the only way the extractor resolves the
    parsed treatment to None."""
    return (
        "<html><head>"
        '<script type="application/ld+json">{"@context":"http://schema.org","@type":"Product",'
        f'"description":"{card_code}",'
        f'"offers":{{"@type":"Offer","price":"{price}","priceCurrency":"JPY","availability":"InStock"}}}}'
        "</script></head><body>"
        '<section id="product-detail">'
        f'<span class="pote">{card_code}</span>'
        f"<h4> {price} 円</h4>"
        "<label> 在庫 :   ○   </label>"
        "</section></body></html>"
    )


def _treatment_conflicts(result) -> list[str]:
    return [r for r in result["fail_reasons"] if r.startswith("treatment_conflict")]


class NonNullExpectationIsUnchanged(unittest.TestCase):
    """The existing contract, restated in full so a regression here cannot
    hide behind the new null-tolerance."""

    def test_expected_parallel_and_parsed_parallel_passes(self):
        result = extract_with_agreement(
            _product_html(marker="パラレル"), PRODUCT_URL, "OP01-002", expected_treatment="parallel"
        )
        self.assertEqual(result["extracted"]["treatment"], "parallel")
        self.assertEqual(_treatment_conflicts(result), [])
        self.assertEqual(result["extraction_status"], "extracted")

    def test_expected_parallel_and_parsed_normal_still_conflicts(self):
        result = extract_with_agreement(
            _product_html(), PRODUCT_URL, "OP01-002", expected_treatment="parallel"
        )
        self.assertEqual(result["extracted"]["treatment"], "normal")
        self.assertEqual(
            _treatment_conflicts(result), ["treatment_conflict:displayed=normal,expected=parallel"]
        )
        self.assertEqual(result["extraction_status"], "fail_closed")

    def test_expected_normal_and_parsed_normal_passes(self):
        result = extract_with_agreement(
            _product_html(marker="ノーマル"), PRODUCT_URL, "OP01-002", expected_treatment="normal"
        )
        self.assertEqual(result["extracted"]["treatment"], "normal")
        self.assertEqual(_treatment_conflicts(result), [])
        self.assertEqual(result["extraction_status"], "extracted")

    def test_expected_normal_and_parsed_parallel_still_conflicts(self):
        result = extract_with_agreement(
            _product_html(marker="パラレル"), PRODUCT_URL, "OP01-002", expected_treatment="normal"
        )
        self.assertEqual(
            _treatment_conflicts(result), ["treatment_conflict:displayed=parallel,expected=normal"]
        )
        self.assertEqual(result["extraction_status"], "fail_closed")


class NullExpectationHasNoTreatmentOpinion(unittest.TestCase):
    def test_expected_null_and_parsed_normal_does_not_conflict(self):
        result = extract_with_agreement(
            _product_html(), PRODUCT_URL, "OP01-002", expected_treatment=None
        )
        self.assertEqual(result["extracted"]["treatment"], "normal")
        self.assertEqual(_treatment_conflicts(result), [])
        self.assertEqual(result["extraction_status"], "extracted")
        self.assertEqual(result["extracted"]["sell_price_jpy"], 500)

    def test_expected_null_and_parsed_parallel_does_not_conflict(self):
        result = extract_with_agreement(
            _product_html(marker="パラレル"), PRODUCT_URL, "OP01-002", expected_treatment=None
        )
        self.assertEqual(result["extracted"]["treatment"], "parallel")
        self.assertEqual(_treatment_conflicts(result), [])
        self.assertEqual(result["extraction_status"], "extracted")

    def test_expected_null_and_parsed_null_does_not_conflict(self):
        result = extract_with_agreement(
            _untitled_html(), PRODUCT_URL, "OP01-002", expected_treatment=None
        )
        self.assertIsNone(result["extracted"]["treatment"])
        self.assertEqual(_treatment_conflicts(result), [])

    def test_null_expectation_does_not_disable_the_other_checks(self):
        """No treatment opinion must not become no opinion at all - a wrong
        card code still fails closed."""
        result = extract_with_agreement(
            _product_html(card_code="OP01-999"), PRODUCT_URL, "OP01-002", expected_treatment=None
        )
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertTrue(any(r.startswith("card_code_conflict") for r in result["fail_reasons"]))
        self.assertEqual(_treatment_conflicts(result), [])

    def test_the_legacy_default_is_still_parallel_when_nothing_is_passed(self):
        """Only a caller with no CardPrint context relies on this, and it must
        not have been loosened into "no expectation"."""
        self.assertEqual(EXPECTED_TREATMENT, "parallel")
        result = extract_with_agreement(_product_html(), PRODUCT_URL, "OP01-002")
        self.assertEqual(
            _treatment_conflicts(result), ["treatment_conflict:displayed=normal,expected=parallel"]
        )


if __name__ == "__main__":
    unittest.main()


# --- writer-level: the same rule against the linked CardPrint row ----------

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from yuyutei_collector.db import Base  # noqa: E402
from yuyutei_collector.models import (  # noqa: E402
    Card,
    CardPrint,
    PriceObservation,
    Source,
    SourceCardMapping,
)
from yuyutei_collector.writer import validate_and_write_observation  # noqa: E402


def _extraction(treatment):
    return {
        "extraction_status": "extracted",
        "fail_reasons": [],
        "extracted": {
            "card_code": "OP01-001",
            "treatment": treatment,
            "sell_price_jpy": 34800,
            "stock_status": "in_stock",
        },
    }


class WriterNullTreatmentTests(unittest.TestCase):
    """validate_and_write_observation compares the extracted treatment with
    the linked print's own. A NULL print treatment is no expectation, so the
    observation must still be written."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine, future=True)()
        self.session.add_all(
            [
                Card(id=11, card_code="OP01-001", name_en="Roronoa Zoro"),
                Source(id=1, name="yuyutei", base_url="https://yuyu-tei.jp"),
            ]
        )
        self.session.flush()

    def tearDown(self):
        self.session.close()

    def _mapping_for(self, treatment, print_id):
        # The collector mirror must accept a NULL treatment at the runtime
        # type layer - the API owns the column and it is still NOT NULL in the
        # database, so this is what a future migration would look like here.
        self.session.add(
            CardPrint(
                id=print_id,
                canonical_card_id=2,
                treatment=treatment,
                verification_status="verified",
            )
        )
        self.session.flush()
        mapping = SourceCardMapping(
            id=print_id, card_id=11, source_id=1, card_print_id=print_id,
            source_card_id="OP01-001", source_url=PRODUCT_URL,
            is_active=True, review_status="approved",
        )
        self.session.add(mapping)
        self.session.flush()
        return mapping

    def _write(self, mapping, extraction):
        return validate_and_write_observation(
            session=self.session,
            mapping=mapping,
            classification="normal_product",
            extraction=extraction,
            http_status=200,
            raw_html="<html>evidence</html>",
            source_url=PRODUCT_URL,
            parser_version="yuyutei-collector-v3",
        )

    def test_a_null_treatment_print_loads_through_the_collector_mirror(self):
        mapping = self._mapping_for(None, print_id=1)
        loaded = self.session.get(CardPrint, mapping.card_print_id)

        self.assertIsNone(loaded.treatment)
        self.assertEqual(loaded.verification_status, "verified")

    def test_null_print_treatment_accepts_a_parsed_normal(self):
        mapping = self._mapping_for(None, print_id=1)

        result = self._write(mapping, _extraction("normal"))

        self.assertTrue(result.written, result.reasons)
        self.assertEqual(
            [r for r in result.reasons if r.startswith("treatment_mismatch_vs_print")], []
        )
        self.session.commit()
        self.assertEqual(self.session.query(PriceObservation).count(), 1)

    def test_null_print_treatment_accepts_a_parsed_parallel(self):
        mapping = self._mapping_for(None, print_id=1)

        result = self._write(mapping, _extraction("parallel"))

        self.assertTrue(result.written, result.reasons)

    def test_non_null_print_treatment_still_rejects_a_mismatch(self):
        mapping = self._mapping_for("parallel", print_id=1)

        result = self._write(mapping, _extraction("normal"))

        self.assertFalse(result.written)
        self.assertTrue(
            any(r.startswith("treatment_mismatch_vs_print") for r in result.reasons), result.reasons
        )

    def test_non_null_print_treatment_still_accepts_a_match(self):
        mapping = self._mapping_for("parallel", print_id=1)

        result = self._write(mapping, _extraction("parallel"))

        self.assertTrue(result.written, result.reasons)
