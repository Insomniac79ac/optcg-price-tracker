"""Proves the single most safety-critical guarantee in this service: a
validate-only run writes ZERO rows, even for a mapping that would otherwise
write successfully.

This matters because validate_and_write_observation() genuinely does
session.add()/flush() a RawSnapshot and a PriceObservation once every gate
passes - nothing is skipped in validate-only mode. The only thing standing
between a validate-only run and a real row is collect.py's session.rollback().
Each test below is paired with a validate_only=False control proving the
fixture really would have written, so the zero-write assertion can never pass
vacuously.

Fully offline: Playwright, the network and the artwork comparison are all
replaced with deterministic doubles.
"""

import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from snkrdunk_collector import collect, writer
from snkrdunk_collector.db import Base
from snkrdunk_collector.release_reference import ReleaseReference
from snkrdunk_collector.models import (
    CanonicalCard,
    Card,
    CardPrint,
    PriceObservation,
    RawSnapshot,
    Source,
    SourceCardMapping,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
PRODUCT_URL = "https://snkrdunk.com/apparels/104428"


class _FakePage:
    def close(self):
        pass


class _FakeContext:
    def new_page(self):
        return _FakePage()

    def close(self):
        pass


class _FakeBrowser:
    def new_context(self, **kwargs):
        return _FakeContext()

    def close(self):
        pass


class _FakeChromium:
    def launch(self, **kwargs):
        return _FakeBrowser()


class _FakePlaywright:
    chromium = _FakeChromium()


@contextmanager
def _fake_sync_playwright():
    yield _FakePlaywright()


class ValidateOnlyNeverWritesTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, future=True)
        session = self.Session()

        session.add_all(
            [
                Card(id=11, card_code="OP01-001", name_en="Roronoa Zoro"),
                Source(id=2, name="snkrdunk", base_url="https://snkrdunk.com"),
                CanonicalCard(
                    id=2,
                    card_code="OP01-001",
                    name_en="Roronoa Zoro",
                    name_jp="ロロノア・ゾロ",
                    rarity="L",
                    original_set_code="OP-01",
                ),
            ]
        )
        session.flush()
        session.add(
            CardPrint(
                id=1,
                canonical_card_id=2,
                language="jp",
                treatment="parallel",
                release_product_code="OP-01",
                artwork_key="abc",
                image_url="https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001_p2.png",
                verification_status="verified",
                is_active=True,
            )
        )
        session.flush()
        session.add(
            SourceCardMapping(
                id=35,
                card_id=11,
                source_id=2,
                card_print_id=1,
                source_card_id="OP01-001",
                source_url=PRODUCT_URL,
                is_active=True,
                review_status="approved",
                manual_verified=True,
            )
        )
        session.commit()
        session.close()

        self.product_html = (FIXTURES_DIR / "product_page_reduced.html").read_text(encoding="utf-8")
        self.history_html = (FIXTURES_DIR / "sales_history_page_reduced.html").read_text(encoding="utf-8")

    def _capture(self, page, url, **kwargs):
        html = self.history_html if "sales-histories" in url else self.product_html
        return {
            "html": html,
            "http_status": 200,
            "classification": "normal_page",
            "final_url": url,
        }

    def _run(self, validate_only: bool, release_name_matches: bool = True):
        """`release_name_matches` swaps in a test-double release reference
        whose official name agrees with the fixture page.

        The fixture is a real OP-01 page, and SNKRDUNK renders OP-01's name as
        the katakana "ロマンスドーン" while Bandai titles it "ROMANCE DAWN" -
        so against the real table it fails the name gate (see
        test_release_reference.py). That naming question is not what this file
        is about: these tests are about whether validate-only persists rows.
        The double keeps the two concerns independent, and
        test_real_op01_release_name_fails_closed below exercises the real
        table deliberately.
        """
        double = ReleaseReference(
            release_product_code="OP-01",
            bandai_official_name="ロマンスドーン" if release_name_matches else "強大な敵",
            source_url="https://example.invalid/test-double",
        )

        session = self.Session()
        try:
            with (
                patch.object(collect, "sync_playwright", _fake_sync_playwright),
                patch.object(collect, "goto_and_capture", self._capture),
                patch.object(collect, "fetch_bytes", lambda page, url: b"image-bytes"),
                patch.object(writer, "get_release_reference", lambda code: double),
                patch.object(
                    collect,
                    "compare_artwork",
                    lambda official, candidate: {
                        "match": True,
                        "hash_distances": {"average_hash": 3, "dhash": 4, "phash": 5},
                        "aspect_ratio_relative_diff": 0.0012,
                    },
                ),
            ):
                outcome = collect.run_one_mapping_detailed(
                    session, 35, validate_only=validate_only, batch_run_id="test-run"
                )
            session.commit()
        finally:
            session.close()

        check = self.Session()
        try:
            return (
                outcome,
                check.query(PriceObservation).count(),
                check.query(RawSnapshot).count(),
            )
        finally:
            check.close()

    def test_control_a_real_write_happens_when_not_validate_only(self):
        """Guards the tests below from passing vacuously: this exact fixture
        genuinely does write when validate_only is False."""
        outcome, observations, snapshots = self._run(validate_only=False)
        self.assertTrue(outcome.written, outcome.reasons)
        self.assertEqual(observations, 1)
        self.assertGreaterEqual(snapshots, 1)

    def test_validate_only_writes_zero_price_observations(self):
        outcome, observations, _ = self._run(validate_only=True)
        self.assertEqual(outcome.stage, "validated_only")
        self.assertEqual(observations, 0)

    def test_validate_only_never_reports_itself_as_written(self):
        """`written` must mean "a row was persisted". Reporting would_write
        as written let batch_complete.mappings_written count writes that
        never happened - the exact number a zero-write audit trusts."""
        outcome, observations, _ = self._run(validate_only=True)
        self.assertFalse(outcome.written)
        self.assertTrue(outcome.would_write)  # every write gate did pass
        self.assertEqual(observations, 0)

    def test_validate_only_writes_zero_raw_snapshots(self):
        _, _, snapshots = self._run(validate_only=True)
        self.assertEqual(snapshots, 0)

    def test_validate_only_still_reports_a_full_identity_verdict(self):
        """Writing nothing must not mean observing nothing - the run is the
        evidence record."""
        outcome, _, _ = self._run(validate_only=True)
        self.assertTrue(outcome.identity_verified, outcome.identity_reasons)
        self.assertEqual(outcome.identity_classification, "PASS")
        self.assertEqual(outcome.price_jpy, 24500)
        self.assertEqual(outcome.condition_label, "B")

    def test_validate_only_retains_complete_a_to_d_conditions(self):
        outcome, _, _ = self._run(validate_only=True)
        self.assertEqual(sorted(outcome.raw_a_to_d), ["A", "B", "C", "D"])
        self.assertEqual(outcome.raw_a_to_d["B"]["price_jpy"], 24500)

    def test_real_op01_release_name_fails_closed_against_the_bandai_table(self):
        """No test double: the genuine reference table against the genuine
        fixture. Proves the gate is live end to end, and that it writes
        nothing when it fails."""
        session = self.Session()
        try:
            with (
                patch.object(collect, "sync_playwright", _fake_sync_playwright),
                patch.object(collect, "goto_and_capture", self._capture),
                patch.object(collect, "fetch_bytes", lambda page, url: b"image-bytes"),
                patch.object(
                    collect,
                    "compare_artwork",
                    lambda official, candidate: {"match": True, "hash_distances": {}},
                ),
            ):
                outcome = collect.run_one_mapping_detailed(
                    session, 35, validate_only=False, batch_run_id="test-real-table"
                )
            session.commit()
        finally:
            session.close()

        check = self.Session()
        try:
            self.assertFalse(outcome.identity_verified)
            self.assertTrue(
                any(r.startswith("release_name_mismatch:") for r in outcome.identity_reasons),
                outcome.identity_reasons,
            )
            self.assertFalse(outcome.written)
            self.assertEqual(check.query(PriceObservation).count(), 0)
        finally:
            check.close()

    def test_validate_only_on_an_unapproved_mapping_writes_nothing(self):
        session = self.Session()
        mapping = session.get(SourceCardMapping, 35)
        mapping.review_status = "needs_review"
        mapping.manual_verified = False
        session.commit()
        session.close()

        outcome, observations, snapshots = self._run(validate_only=True)
        self.assertEqual(observations, 0)
        self.assertEqual(snapshots, 0)
        # Identity is still established despite the mapping being unapproved.
        self.assertTrue(outcome.identity_verified, outcome.identity_reasons)


if __name__ == "__main__":
    unittest.main()
