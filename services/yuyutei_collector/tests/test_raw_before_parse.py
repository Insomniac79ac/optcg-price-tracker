"""Raw-before-parse lineage tests; all responses and databases are local fakes."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from yuyutei_collector import collect, telemetry
from yuyutei_collector.batch import run_batch
from yuyutei_collector.browser import classify_capture as real_classify_capture
from yuyutei_collector.collect import PARSER_VERSION
from yuyutei_collector.db import Base
from yuyutei_collector.models import (
    CanonicalCard,
    CardPrint,
    PriceObservation,
    RawSnapshot,
    Source,
    SourceCardMapping,
    SourceCollectionAttempt,
)
from yuyutei_collector.telemetry import RawSnapshotPersistenceError


PRODUCT_URL = "https://yuyu-tei.jp/sell/opc/card/op01/10002"
HOMEPAGE_URL = "https://yuyu-tei.jp/"
PRODUCT_HTML = (
    "<html><body>OP01-001 " + ("product evidence " * 80) + "</body></html>"
)
HOMEPAGE_HTML = "<html><body>遊々亭 " + ("homepage " * 80) + "</body></html>"

GOOD_EXTRACTION = {
    "extraction_status": "extracted",
    "fail_reasons": [],
    "extracted": {
        "card_code": "OP01-001",
        "treatment": "parallel",
        "sell_price_jpy": 34_800,
        "stock_status": "out_of_stock",
        "promotion_state": "sale",
    },
}

IDENTITY_FAILURE = {
    "extraction_status": "fail_closed",
    "fail_reasons": ["card_code_conflict:displayed=OP01-099,expected=OP01-001"],
    "extracted": {
        "card_code": "OP01-099",
        "treatment": "parallel",
        "sell_price_jpy": 34_800,
        "stock_status": "out_of_stock",
        "promotion_state": "none",
    },
}


class RawBeforeParseTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        database_path = Path(self.tempdir.name) / "collector.sqlite3"
        self.engine = create_engine(f"sqlite:///{database_path}")

        @event.listens_for(self.engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, future=True)
        with self.Session() as session:
            source = Source(name="yuyutei", base_url=HOMEPAGE_URL)
            canonical = CanonicalCard(card_code="OP01-001")
            session.add_all([source, canonical])
            session.flush()
            card_print = CardPrint(
                canonical_card_id=canonical.id,
                treatment="parallel",
                verification_status="verified",
                is_active=True,
            )
            session.add(card_print)
            session.flush()
            mapping = SourceCardMapping(
                source_id=source.id,
                card_print_id=card_print.id,
                source_card_id="OP01-001",
                source_url=PRODUCT_URL,
                is_active=True,
                review_status="approved",
            )
            session.add(mapping)
            session.commit()
            self.source_id = source.id
            self.mapping_id = mapping.id

        self.patchers = [
            patch.object(telemetry, "SessionLocal", self.Session),
            patch("yuyutei_collector.batch._mapping_delay_s", return_value=0.0),
            patch.object(collect, "pkg_version", return_value="test"),
            patch.object(collect, "_release_browser_objects", return_value=None),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

        playwright = MagicMock()
        playwright.__enter__.return_value = playwright
        playwright.__exit__.return_value = False
        self.sync_playwright_patch = patch.object(
            collect, "sync_playwright", return_value=playwright
        )
        self.sync_playwright_patch.start()
        self.addCleanup(self.sync_playwright_patch.stop)

    def tearDown(self):
        self.engine.dispose()
        self.tempdir.cleanup()

    def _normal_homepage(self):
        return {
            "final_url": HOMEPAGE_URL,
            "http_status": 200,
            "navigation_ok": True,
            "page_title": "遊々亭",
            "classification": "normal_product",
            "classification_evidence": ["expected_content_present=True"],
            "html": HOMEPAGE_HTML,
        }

    def _product(self, *, status=200, html=PRODUCT_HTML):
        return {
            "final_url": PRODUCT_URL,
            "http_status": status,
            "navigation_ok": 200 <= status < 300,
            "page_title": "OP01-001",
            "html_bytes": len(html.encode("utf-8")),
            "elapsed_s": 0.1,
            "html": html,
        }

    def _run(self, *, homepage=None, product=None, extraction=GOOD_EXTRACTION, validate_only=False):
        homepage = self._normal_homepage() if homepage is None else homepage
        product = self._product() if product is None else product
        with (
            patch.object(collect, "warm_up_homepage", return_value=homepage),
            patch.object(collect, "goto_and_capture_raw", return_value=product),
            patch.object(collect, "extract_with_agreement", return_value=extraction),
        ):
            return run_batch(
                session_factory=self.Session,
                validate_only=validate_only,
            )

    def _rows(self):
        with self.Session() as session:
            attempts = session.scalars(select(SourceCollectionAttempt)).all()
            snapshots = session.scalars(select(RawSnapshot)).all()
            observations = session.scalars(select(PriceObservation)).all()
            return attempts, snapshots, observations

    def _assert_snapshot_already_linked(self):
        with self.Session() as observer:
            snapshots = observer.scalars(select(RawSnapshot)).all()
            attempt = observer.scalars(select(SourceCollectionAttempt)).one()
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(attempt.raw_snapshot_id, snapshots[0].id)

    def test_success_persists_and_links_before_classification_and_parsing(self):
        def classify_after_persist(step, expected_markers):
            self._assert_snapshot_already_linked()
            return real_classify_capture(step, expected_markers)

        def parse_after_persist(*_args):
            self._assert_snapshot_already_linked()
            return GOOD_EXTRACTION

        with (
            patch.object(collect, "warm_up_homepage", return_value=self._normal_homepage()),
            patch.object(collect, "goto_and_capture_raw", return_value=self._product()),
            patch.object(collect, "classify_capture", side_effect=classify_after_persist),
            patch.object(collect, "extract_with_agreement", side_effect=parse_after_persist),
        ):
            result = run_batch(session_factory=self.Session)

        attempts, snapshots, observations = self._rows()
        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.results), 1)
        self.assertEqual((len(attempts), len(snapshots), len(observations)), (1, 1, 1))
        attempt, snapshot, observation = attempts[0], snapshots[0], observations[0]
        self.assertEqual(attempt.status, "written")
        self.assertEqual(attempt.raw_snapshot_id, snapshot.id)
        self.assertEqual(attempt.price_observation_id, observation.id)
        self.assertEqual(observation.raw_snapshot_id, snapshot.id)
        self.assertEqual(observation.price_jpy, 34_800)
        self.assertEqual(observation.price_type, "sell")
        self.assertEqual(observation.stock_status, "out_of_stock")
        self.assertEqual(observation.promotion_state, "sale")

    def test_parser_failure_keeps_raw_and_writes_no_observation(self):
        with (
            patch.object(collect, "warm_up_homepage", return_value=self._normal_homepage()),
            patch.object(collect, "goto_and_capture_raw", return_value=self._product()),
            patch.object(collect, "extract_with_agreement", side_effect=ValueError("bad markup")),
        ):
            result = run_batch(session_factory=self.Session)

        attempts, snapshots, observations = self._rows()
        self.assertEqual(result.results[0].failure_stage, "extraction")
        self.assertTrue(result.results[0].reasons[0].startswith("parser_failure:"))
        self.assertEqual(attempts[0].status, "operational_error")
        self.assertEqual(attempts[0].failure_stage, "extraction")
        self.assertEqual(attempts[0].raw_snapshot_id, snapshots[0].id)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(observations, [])

    def test_identity_validation_failure_keeps_raw_and_writes_no_observation(self):
        result = self._run(extraction=IDENTITY_FAILURE)
        attempts, snapshots, observations = self._rows()
        self.assertEqual(result.results[0].stage, "validation_failed")
        self.assertEqual(attempts[0].status, "validation_failed")
        self.assertIn("card_code_conflict", attempts[0].failure_reason)
        self.assertEqual(attempts[0].raw_snapshot_id, snapshots[0].id)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(observations, [])

    def test_source_403_with_body_is_replayable_and_links_to_denial(self):
        denied_homepage = {
            "final_url": HOMEPAGE_URL,
            "http_status": 403,
            "navigation_ok": False,
            "page_title": "403 Forbidden",
            "classification": "static_403",
            "classification_evidence": ["http_403"],
            "html": "<html><body>denied</body></html>",
        }
        product = MagicMock()
        with (
            patch.object(collect, "warm_up_homepage", return_value=denied_homepage),
            patch.object(collect, "goto_and_capture_raw", product),
            patch.object(collect, "extract_with_agreement") as extractor,
        ):
            result = run_batch(session_factory=self.Session)

        attempts, snapshots, observations = self._rows()
        self.assertTrue(result.results[0].source_denied)
        self.assertEqual(attempts[0].status, "no_extraction_attempted")
        self.assertTrue(attempts[0].source_denied)
        self.assertEqual(attempts[0].raw_snapshot_id, snapshots[0].id)
        self.assertEqual(snapshots[0].http_status, 403)
        self.assertEqual(snapshots[0].raw_content, denied_homepage["html"])
        self.assertEqual(observations, [])
        product.assert_not_called()
        extractor.assert_not_called()

    def test_product_403_is_persisted_before_source_denial_classification(self):
        denied_product = self._product(
            status=403,
            html="<html><body>product request denied</body></html>",
        )

        def classify_after_persist(step, expected_markers):
            self._assert_snapshot_already_linked()
            return real_classify_capture(step, expected_markers)

        with (
            patch.object(collect, "warm_up_homepage", return_value=self._normal_homepage()),
            patch.object(collect, "goto_and_capture_raw", return_value=denied_product),
            patch.object(collect, "classify_capture", side_effect=classify_after_persist),
            patch.object(collect, "extract_with_agreement") as extractor,
        ):
            result = run_batch(session_factory=self.Session)

        attempts, snapshots, observations = self._rows()
        self.assertTrue(result.results[0].source_denied)
        self.assertEqual(attempts[0].status, "no_extraction_attempted")
        self.assertEqual(attempts[0].raw_snapshot_id, snapshots[0].id)
        self.assertEqual(snapshots[0].http_status, 403)
        self.assertEqual(snapshots[0].raw_content, denied_product["html"])
        self.assertEqual(observations, [])
        extractor.assert_not_called()

    def test_navigation_failure_without_body_keeps_null_snapshot_link(self):
        navigation_error = {"error": "TimeoutError: navigation timed out", "elapsed_s": 30.0}
        result = self._run(product=navigation_error)
        attempts, snapshots, observations = self._rows()
        self.assertEqual(result.results[0].stage, "no_extraction_attempted")
        self.assertEqual(result.results[0].failure_stage, "product")
        self.assertIsNone(attempts[0].raw_snapshot_id)
        self.assertEqual(snapshots, [])
        self.assertEqual(observations, [])

    def test_later_writer_rollback_cannot_delete_snapshot_or_attempt_link(self):
        real_writer = collect.validate_and_write_observation

        def flush_then_fail(**kwargs):
            write_result = real_writer(**kwargs)
            self.assertTrue(write_result.written)
            raise RuntimeError("after observation flush")

        with (
            patch.object(collect, "warm_up_homepage", return_value=self._normal_homepage()),
            patch.object(collect, "goto_and_capture_raw", return_value=self._product()),
            patch.object(collect, "extract_with_agreement", return_value=GOOD_EXTRACTION),
            patch.object(collect, "validate_and_write_observation", side_effect=flush_then_fail),
        ):
            result = run_batch(session_factory=self.Session)

        attempts, snapshots, observations = self._rows()
        self.assertEqual(result.results[0].stage, "operational_error")
        self.assertEqual(result.results[0].failure_stage, "write")
        self.assertEqual(attempts[0].status, "operational_error")
        self.assertEqual(attempts[0].raw_snapshot_id, snapshots[0].id)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(observations, [])

    def test_snapshot_persistence_failure_stops_before_parser_and_observation(self):
        with (
            patch.object(collect, "warm_up_homepage", return_value=self._normal_homepage()),
            patch.object(collect, "goto_and_capture_raw", return_value=self._product()),
            patch.object(
                collect,
                "persist_response_snapshot",
                side_effect=RawSnapshotPersistenceError("database_error:IntegrityError"),
            ),
            patch.object(collect, "extract_with_agreement") as extractor,
        ):
            result = run_batch(session_factory=self.Session)

        attempts, snapshots, observations = self._rows()
        self.assertEqual(result.results[0].stage, "operational_error")
        self.assertEqual(result.results[0].failure_stage, "write")
        self.assertTrue(
            result.results[0].reasons[0].startswith("raw_snapshot_persistence_failed:")
        )
        self.assertEqual(attempts[0].status, "operational_error")
        self.assertIsNone(attempts[0].raw_snapshot_id)
        self.assertEqual(snapshots, [])
        self.assertEqual(observations, [])
        extractor.assert_not_called()

    def test_validate_only_makes_no_persistent_database_writes(self):
        with patch.object(collect, "persist_response_snapshot") as persist:
            result = self._run(validate_only=True)

        attempts, snapshots, observations = self._rows()
        self.assertEqual(result.results[0].stage, "validated_only")
        self.assertTrue(result.results[0].written)
        self.assertEqual(attempts, [])
        self.assertEqual(snapshots, [])
        self.assertEqual(observations, [])
        persist.assert_not_called()

    def test_same_batch_mapping_snapshot_call_is_application_idempotent(self):
        with self.Session() as session:
            session.add(
                SourceCollectionAttempt(
                    batch_run_id="fixed-run",
                    source_id=self.source_id,
                    source_card_mapping_id=self.mapping_id,
                    selection_ordinal=1,
                )
            )
            session.commit()

        kwargs = dict(
            bind=self.engine,
            source_id=self.source_id,
            source_url=PRODUCT_URL,
            http_status=200,
            raw_content=PRODUCT_HTML,
            parser_version=PARSER_VERSION,
            batch_run_id="fixed-run",
            source_card_mapping_id=self.mapping_id,
        )
        first = telemetry.persist_response_snapshot(**kwargs)
        second = telemetry.persist_response_snapshot(**kwargs)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.raw_snapshot_id, second.raw_snapshot_id)
        attempts, snapshots, observations = self._rows()
        self.assertEqual(len(attempts), 1)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(attempts[0].raw_snapshot_id, snapshots[0].id)
        self.assertEqual(observations, [])

    def test_same_attempt_with_different_response_fails_closed_without_duplicate(self):
        with self.Session() as session:
            session.add(
                SourceCollectionAttempt(
                    batch_run_id="fixed-run",
                    source_id=self.source_id,
                    source_card_mapping_id=self.mapping_id,
                    selection_ordinal=1,
                )
            )
            session.commit()

        kwargs = dict(
            bind=self.engine,
            source_id=self.source_id,
            source_url=PRODUCT_URL,
            http_status=200,
            raw_content=PRODUCT_HTML,
            parser_version=PARSER_VERSION,
            batch_run_id="fixed-run",
            source_card_mapping_id=self.mapping_id,
        )
        first = telemetry.persist_response_snapshot(**kwargs)
        with self.assertRaisesRegex(
            RawSnapshotPersistenceError, "attempt_snapshot_conflict"
        ):
            telemetry.persist_response_snapshot(
                **{**kwargs, "raw_content": PRODUCT_HTML + "changed"}
            )

        attempts, snapshots, observations = self._rows()
        self.assertEqual(len(attempts), 1)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(attempts[0].raw_snapshot_id, first.raw_snapshot_id)
        self.assertEqual(observations, [])


if __name__ == "__main__":
    unittest.main()
