"""A CardPrint with treatment = NULL carries no Atlas classification, so
SNKRDUNK must hold no treatment expectation for it - and must not fail the
page closed because the page shows one.

Same rule as the Yuyu-Tei collector's
tests/test_null_treatment_expectation.py. Every other SNKRDUNK gate -
card code, rarity, language, release, floor availability - is untouched, and
a non-null treatment is still matched exactly as strictly as before."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from snkrdunk_collector.db import Base
from snkrdunk_collector.extractor import extract_product
from snkrdunk_collector.models import CardPrint

FIXTURES = Path(__file__).parent / "fixtures"
PRODUCT_URL = "https://snkrdunk.com/en/trading-cards/12345"


def _load_html() -> str:
    return (FIXTURES / "product_page_reduced.html").read_text(encoding="utf-8")


def _treatment_conflicts(result) -> list[str]:
    return [r for r in result["fail_reasons"] if r.startswith("treatment_conflict")]


class TestNonNullExpectationUnchanged:
    def test_matching_treatment_passes(self):
        result = extract_product(
            _load_html(), PRODUCT_URL, expected_card_code="OP01-001", expected_treatment="parallel"
        )
        assert result["extraction_status"] == "extracted"
        assert _treatment_conflicts(result) == []

    def test_mismatched_treatment_still_fails_closed(self):
        result = extract_product(
            _load_html(), PRODUCT_URL, expected_card_code="OP01-001", expected_treatment="normal"
        )
        assert result["extraction_status"] == "fail_closed"
        assert _treatment_conflicts(result) == [
            "treatment_conflict:displayed=parallel,expected=normal"
        ]


class TestNullExpectationHasNoOpinion:
    def test_null_expectation_does_not_conflict_with_a_parsed_treatment(self):
        result = extract_product(
            _load_html(), PRODUCT_URL, expected_card_code="OP01-001", expected_treatment=None
        )
        assert result["extracted"]["treatment"] == "parallel"
        assert _treatment_conflicts(result) == []
        assert result["extraction_status"] == "extracted"

    def test_null_expectation_does_not_disable_the_other_gates(self):
        """No treatment opinion is not no opinion - a wrong card code still
        fails closed."""
        result = extract_product(
            _load_html(), PRODUCT_URL, expected_card_code="OP01-002", expected_treatment=None
        )
        assert result["extraction_status"] == "fail_closed"
        assert any(r.startswith("card_code_conflict:") for r in result["fail_reasons"])
        assert _treatment_conflicts(result) == []


class TestMirrorAcceptsNull:
    """The collector's mirror of card_prints must load a future NULL rather
    than tripping the mapper. The API owns the column and it is still NOT
    NULL in the database; this mirror emits no DDL of its own."""

    @pytest.fixture()
    def session(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine, future=True)()
        try:
            yield session
        finally:
            session.close()

    def test_a_null_treatment_print_round_trips(self, session):
        session.add(
            CardPrint(
                id=1, canonical_card_id=2, language="jp", treatment=None,
                verification_status="verified",
            )
        )
        session.commit()

        loaded = session.get(CardPrint, 1)
        assert loaded.treatment is None
        assert loaded.verification_status == "verified"

    def test_a_classified_print_still_round_trips(self, session):
        session.add(
            CardPrint(
                id=2, canonical_card_id=2, language="jp", treatment="parallel",
                verification_status="verified",
            )
        )
        session.commit()

        assert session.get(CardPrint, 2).treatment == "parallel"
