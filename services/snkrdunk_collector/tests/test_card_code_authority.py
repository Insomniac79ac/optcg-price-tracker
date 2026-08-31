"""Offline tests for the card-code authority hierarchy.

The rule under test: SNKRDUNK may never supply both the observed AND the
expected card code. The expected value comes from Bandai card-level evidence
where it exists, otherwise a VERIFIED Yuyu-Tei product for the same print, and
otherwise nothing at all - in which case validation fails closed.

Release/set identity does not use this hierarchy; Bandai stays its sole
authority, and that separation is asserted here too.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from snkrdunk_collector.card_code_authority import (
    AUTHORITY_BANDAI,
    AUTHORITY_YUYUTEI,
    card_code_from_bandai_image_url,
    resolve_expected_card_code,
)
from snkrdunk_collector.db import Base
from snkrdunk_collector.models import (
    ReleaseProduct,
    CanonicalCard,
    Card,
    CardPrint,
    Source,
    SourceCardMapping,
)
from snkrdunk_collector.release_reference import MATCH_BANDAI_OFFICIAL
from snkrdunk_collector.writer import validate_and_write_observation

BANDAI_IMAGE = "https://www.onepiece-cardgame.com/images/cardlist/card/OP04-118.png?2606"
YUYUTEI_URL = "https://yuyu-tei.jp/sell/opc/card/op04/10141"
SNKRDUNK_URL = "https://snkrdunk.com/apparels/126173"


class BandaiImageUrlParsingTests(unittest.TestCase):
    def test_parses_the_card_code_bandai_encodes_in_its_own_path(self):
        self.assertEqual(card_code_from_bandai_image_url(BANDAI_IMAGE), "OP04-118")

    def test_parallel_artwork_suffix_is_not_part_of_the_card_code(self):
        url = "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001_p2.png?2"
        self.assertEqual(card_code_from_bandai_image_url(url), "OP01-001")

    def test_non_bandai_host_is_rejected(self):
        self.assertIsNone(
            card_code_from_bandai_image_url("https://cdn.snkrdunk.com/upload/OP04-118.png")
        )

    def test_missing_or_malformed_url_is_none(self):
        self.assertIsNone(card_code_from_bandai_image_url(None))
        self.assertIsNone(card_code_from_bandai_image_url(""))
        self.assertIsNone(
            card_code_from_bandai_image_url("https://www.onepiece-cardgame.com/images/other/x.png")
        )


class AuthorityResolutionTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, future=True)
        self.session = self.Session()

        self.session.add_all(
            [
                Card(id=22, card_code="OP04-118", name_en="Nefeltari Vivi"),
                Source(id=1, name="yuyutei", base_url="https://yuyu-tei.jp"),
                Source(id=2, name="snkrdunk", base_url="https://snkrdunk.com"),
                CanonicalCard(
                    id=18, card_code="OP04-118", name_en="Nefeltari Vivi",
                    name_jp="ネフェルタリ・ビビ", rarity="SEC", original_set_code="OP-04",
                ),
            ]
        )
        self.session.flush()

    def tearDown(self):
        self.session.close()

    def _print(self, image_url):
        # Release verification resolves the product from the catalogue, so the
        # print names a real verified OP-04 row - see release_identity.py.
        if self.session.get(ReleaseProduct, 104) is None:
            self.session.add(
                ReleaseProduct(
                    id=104, source_catalogue="bandai_jp", official_code="OP-04",
                    display_name="謀略の王国", first_seen_name="謀略の王国",
                    source_series_id="569004", verification_status="verified",
                )
            )
            self.session.flush()
        card_print = CardPrint(
            id=18, canonical_card_id=18, language="jp", treatment="normal",
            release_product_code="OP-04", release_product_id=104, image_url=image_url,
            verification_status="verified", is_active=True,
        )
        self.session.add(card_print)
        self.session.flush()
        return card_print

    def _yuyutei(self, review_status="approved", manual_verified=True, card_code="OP04-118"):
        mapping = SourceCardMapping(
            id=32, card_id=22, source_id=1, card_print_id=18,
            source_card_id=card_code, source_url=YUYUTEI_URL,
            is_active=True, review_status=review_status, manual_verified=manual_verified,
        )
        self.session.add(mapping)
        self.session.flush()
        return mapping

    # --- tier 1: Bandai ----------------------------------------------------

    def test_bandai_evidence_available_is_accepted_as_the_authority(self):
        card_print = self._print(BANDAI_IMAGE)
        self._yuyutei()
        resolved = resolve_expected_card_code(self.session, card_print)
        self.assertEqual(resolved.card_code, "OP04-118")
        self.assertEqual(resolved.authority, AUTHORITY_BANDAI)
        self.assertEqual(resolved.evidence_url, BANDAI_IMAGE)

    def test_bandai_wins_over_yuyutei_when_both_exist(self):
        card_print = self._print(BANDAI_IMAGE)
        self._yuyutei()
        self.assertEqual(
            resolve_expected_card_code(self.session, card_print).authority, AUTHORITY_BANDAI
        )

    # --- tier 2: verified Yuyu-Tei fallback --------------------------------

    def test_yuyutei_fallback_accepted_when_bandai_evidence_absent(self):
        card_print = self._print(None)
        self._yuyutei()
        resolved = resolve_expected_card_code(self.session, card_print)
        self.assertEqual(resolved.card_code, "OP04-118")
        self.assertEqual(resolved.authority, AUTHORITY_YUYUTEI)
        self.assertEqual(resolved.evidence_url, YUYUTEI_URL)

    def test_unverified_yuyutei_mapping_cannot_establish_the_expected_code(self):
        """approved alone is not enough - manual_verified is required, the
        exact distinction the 2026-08-10 incident turned on."""
        card_print = self._print(None)
        self._yuyutei(manual_verified=False)
        self.assertIsNone(resolve_expected_card_code(self.session, card_print))

    def test_needs_review_yuyutei_mapping_cannot_establish_the_expected_code(self):
        card_print = self._print(None)
        self._yuyutei(review_status="needs_review")
        self.assertIsNone(resolve_expected_card_code(self.session, card_print))

    def test_inactive_yuyutei_mapping_cannot_establish_the_expected_code(self):
        card_print = self._print(None)
        mapping = self._yuyutei()
        mapping.is_active = False
        self.session.flush()
        self.assertIsNone(resolve_expected_card_code(self.session, card_print))

    def test_yuyutei_mapping_for_a_different_print_is_not_used(self):
        card_print = self._print(None)
        other = SourceCardMapping(
            id=99, card_id=22, source_id=1, card_print_id=999,
            source_card_id="OP04-999", source_url=YUYUTEI_URL,
            is_active=True, review_status="approved", manual_verified=True,
        )
        self.session.add(other)
        self.session.flush()
        self.assertIsNone(resolve_expected_card_code(self.session, card_print))

    # --- SNKRDUNK is never an authority ------------------------------------

    def test_snkrdunk_mapping_cannot_establish_its_own_expected_code(self):
        """Even a fully approved, manually verified SNKRDUNK mapping for the
        same print must not be usable as the expected value."""
        card_print = self._print(None)
        snkrdunk = SourceCardMapping(
            id=52, card_id=22, source_id=2, card_print_id=18,
            source_card_id="OP04-118", source_url=SNKRDUNK_URL,
            is_active=True, review_status="approved", manual_verified=True,
        )
        self.session.add(snkrdunk)
        self.session.flush()
        self.assertIsNone(resolve_expected_card_code(self.session, card_print))

    def test_no_evidence_at_all_returns_none_rather_than_guessing(self):
        card_print = self._print(None)
        self.assertIsNone(resolve_expected_card_code(self.session, card_print))

    def test_missing_card_print_returns_none(self):
        self.assertIsNone(resolve_expected_card_code(self.session, None))


class AuthorityInValidationTests(AuthorityResolutionTestCase):
    """The resolved authority actually drives writer.validate_identity."""

    GOOD = {
        "card_name": "ネフェルタリ・ビビ",
        "card_code": "OP04-118",
        "rarity": "SEC",
        "treatment": "normal",
        "page_language": "ja",
        "release_text": "ブースターパック 謀略の王国",
        "release_product_code": "OP-04",
        "raw_floor_jpy": 1000,
        "raw_floor_condition": "B",
    }

    def _snkrdunk_mapping(self):
        mapping = SourceCardMapping(
            id=52, card_id=22, source_id=2, card_print_id=18,
            source_card_id="OP04-118", source_url=SNKRDUNK_URL,
            is_active=True, review_status="approved", manual_verified=True,
        )
        self.session.add(mapping)
        self.session.flush()
        return mapping

    def _validate(self, extracted):
        return validate_and_write_observation(
            session=self.session,
            mapping=self._snkrdunk_mapping(),
            classification="normal_page",
            extraction={"extraction_status": "extracted", "fail_reasons": [], "extracted": extracted},
            artwork_comparison={"match": True, "hash_distances": {"average_hash": 3}},
            http_status=200,
            raw_html="<html>evidence</html>",
            source_url=SNKRDUNK_URL,
            parser_version="snkrdunk-collector-v2",
        )

    def test_bandai_backed_identity_passes_and_records_its_authority(self):
        self._print(BANDAI_IMAGE)
        result = self._validate(dict(self.GOOD))
        self.assertTrue(result.identity_verified, result.identity_reasons)
        self.assertEqual(result.card_code_authority, AUTHORITY_BANDAI)
        self.assertEqual(result.card_code_evidence, BANDAI_IMAGE)

    def test_yuyutei_backed_identity_passes_and_records_its_authority(self):
        self._print(None)
        self._yuyutei()
        result = self._validate(dict(self.GOOD))
        self.assertTrue(result.identity_verified, result.identity_reasons)
        self.assertEqual(result.card_code_authority, AUTHORITY_YUYUTEI)
        self.assertEqual(result.card_code_evidence, YUYUTEI_URL)

    def test_observed_code_mismatch_still_fails_under_bandai_authority(self):
        self._print(BANDAI_IMAGE)
        result = self._validate(dict(self.GOOD, card_code="OP04-999"))
        self.assertFalse(result.identity_verified)
        reason = next(r for r in result.identity_reasons if r.startswith("card_code_mismatch:"))
        self.assertIn("expected=OP04-118", reason)
        self.assertIn(f"authority={AUTHORITY_BANDAI}", reason)

    def test_observed_code_mismatch_still_fails_under_yuyutei_authority(self):
        self._print(None)
        self._yuyutei()
        result = self._validate(dict(self.GOOD, card_code="OP04-999"))
        self.assertFalse(result.identity_verified)
        reason = next(r for r in result.identity_reasons if r.startswith("card_code_mismatch:"))
        self.assertIn(f"authority={AUTHORITY_YUYUTEI}", reason)

    def test_no_authority_fails_closed_rather_than_trusting_snkrdunk(self):
        """The SNKRDUNK mapping's own source_card_id equals the observed code
        here - under the old gate that would have passed. It must not."""
        self._print(None)
        result = self._validate(dict(self.GOOD))
        self.assertFalse(result.identity_verified)
        self.assertTrue(
            any(r.startswith("card_code_authority_missing:") for r in result.identity_reasons),
            result.identity_reasons,
        )

    def test_release_authority_stays_bandai_under_yuyutei_card_code_fallback(self):
        """Section 4: the Yuyu-Tei fallback applies to card codes only. The
        release name must still match Bandai."""
        self._print(None)
        self._yuyutei()
        result = self._validate(dict(self.GOOD))
        self.assertEqual(result.card_code_authority, AUTHORITY_YUYUTEI)
        self.assertEqual(result.release_name_match_authority, MATCH_BANDAI_OFFICIAL)

    def test_wrong_release_name_still_fails_under_yuyutei_card_code_fallback(self):
        self._print(None)
        self._yuyutei()
        result = self._validate(dict(self.GOOD, release_text="ブースターパック 強大な敵"))
        self.assertFalse(result.identity_verified)
        self.assertTrue(any(r.startswith("release_name_mismatch:") for r in result.identity_reasons))


if __name__ == "__main__":
    unittest.main()
