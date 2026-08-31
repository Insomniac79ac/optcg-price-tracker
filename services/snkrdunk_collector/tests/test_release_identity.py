"""Release verification against the print's own ReleaseProduct.

WHAT THIS REPLACED AND WHY. Release verification used to resolve the expected
release name from `RELEASE_REFERENCES[card_print.release_product_code]`, a
five-entry table. Measured on the 2026-08-31 canary of 30 approved staging
mappings, that refused 20 of them:

  * 18 named an UNCODED Bandai product (`release_product_code IS NULL`), which
    no code-keyed table can ever cover;
  * 2 named ST-04, a coded product simply not in the five.

and separately, every REPRINT tripped `release_product_mismatch`, because
SNKRDUNK derives a product code from the displayed card code (ST01-012 ->
"ST-01") and the print legitimately belonged to another product. Staging
mapping 88 is exactly that: ST01-012 printed in OP-03, whose listing carried
Bandai's official OP-03 name and was refused anyway.

The catalogue already holds both facts, so the collector now reads them.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from snkrdunk_collector.db import Base
from snkrdunk_collector.models import (
    CanonicalCard,
    CardPrint,
    ReleaseProduct,
    ReleaseProductAlias,
)
from snkrdunk_collector.release_identity import (
    MATCH_BANDAI_OFFICIAL,
    MATCH_SOURCE_RENDERING,
    resolve_release_identity,
)


class ReleaseIdentityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine, future=True)()
        self.session.add(
            CanonicalCard(
                id=1, card_code="ST01-012", name_en="Monkey.D.Luffy",
                name_jp="モンキー・D・ルフィ", rarity="SR",
            )
        )
        self.session.flush()

    def tearDown(self):
        self.session.close()

    def _product(self, pid, code, name, **kw):
        row = ReleaseProduct(
            id=pid,
            source_catalogue="bandai_jp",
            official_code=code,
            display_name=name,
            first_seen_name=kw.pop("first_seen_name", name),
            source_series_id=str(pid),
            verification_status=kw.pop("verification_status", "verified"),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def _print(self, pid, product, **kw):
        row = CardPrint(
            id=pid,
            canonical_card_id=1,
            language="jp",
            treatment=None,
            release_product_code=product.official_code if product else None,
            release_product_id=product.id if product else None,
            artwork_key=f"k{pid}",
            verification_status="verified",
            is_active=True,
            **kw,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def _alias(self, product, name, kind):
        self.session.add(
            ReleaseProductAlias(product_id=product.id, alias_name=name, alias_kind=kind)
        )
        self.session.flush()

    # --- D. coded products ---------------------------------------------------

    def test_a_coded_product_validates_from_the_catalogue(self):
        product = self._product(1, "OP-03", "強大な敵")
        identity = resolve_release_identity(self.session, self._print(10, product)).identity
        self.assertIsNotNone(identity)
        self.assertEqual(identity.official_code, "OP-03")
        self.assertFalse(identity.is_uncoded)
        self.assertEqual(identity.classify_match("ブースターパック 強大な敵"), MATCH_BANDAI_OFFICIAL)

    def test_the_five_static_references_still_answer(self):
        """I. OP-01..OP-04 and EB-01 keep working, including OP-01's katakana
        rendering, which Bandai does NOT publish and which is therefore
        reported as a source rendering rather than a Bandai attestation."""
        product = self._product(1, "OP-01", "ROMANCE DAWN")
        identity = resolve_release_identity(self.session, self._print(10, product)).identity
        self.assertEqual(identity.classify_match("ROMANCE DAWN"), MATCH_BANDAI_OFFICIAL)
        self.assertEqual(identity.classify_match("ブースターパック ロマンスドーン"), MATCH_SOURCE_RENDERING)

    # --- E. uncoded products -------------------------------------------------

    def test_an_uncoded_product_validates_without_a_code(self):
        product = self._product(2, None, "プレミアムカードコレクション 25周年エディション")
        identity = resolve_release_identity(self.session, self._print(11, product)).identity
        self.assertIsNotNone(identity)
        self.assertTrue(identity.is_uncoded)
        self.assertIsNone(identity.official_code)
        self.assertEqual(
            identity.classify_match("プレミアムカードコレクション25周年エディション"),
            MATCH_BANDAI_OFFICIAL,
        )

    def test_an_uncoded_product_is_described_without_inventing_a_code(self):
        """A refusal has to name the product, and an invented code is
        indistinguishable from a published one once written down."""
        product = self._product(2, None, "スタンダードバトルパック Vol.3")
        identity = resolve_release_identity(self.session, self._print(11, product)).identity
        described = identity.describe()
        self.assertIn("uncoded product #2", described)
        self.assertIn("スタンダードバトルパック Vol.3", described)

    def test_a_source_rendering_alias_answers_for_an_uncoded_product(self):
        product = self._product(2, None, "ファミリーデッキセット")
        self._alias(product, "ファミリーデッキセット -海軍-", "source_rendering")
        identity = resolve_release_identity(self.session, self._print(11, product)).identity
        self.assertEqual(
            identity.classify_match("ファミリーデッキセット -海軍-"), MATCH_SOURCE_RENDERING
        )

    # --- F. the reprint case -------------------------------------------------

    def test_a_reprint_validates_against_its_own_product_not_the_code_prefix(self):
        """Staging mapping 88, as a unit test.

        ST01-012 printed in OP-03. The card code's prefix says "ST-01"; the
        print says OP-03; the listing says OP-03's Bandai name. It validates.
        """
        st01 = self._product(1, "ST-01", "スタートデッキ 麦わらの一味")
        op03 = self._product(3, "OP-03", "強大な敵")
        original = self._print(20, st01)
        reprint = self._print(21, op03)

        original_identity = resolve_release_identity(self.session, original).identity
        reprint_identity = resolve_release_identity(self.session, reprint).identity

        self.assertEqual(original_identity.official_code, "ST-01")
        self.assertEqual(reprint_identity.official_code, "OP-03")
        # Each validates against ITS OWN product's name...
        self.assertIsNotNone(original_identity.classify_match("スタートデッキ 麦わらの一味"))
        self.assertIsNotNone(reprint_identity.classify_match("ブースターパック 強大な敵"))
        # ...and neither accepts the other's.
        self.assertIsNone(original_identity.classify_match("ブースターパック 強大な敵"))
        self.assertIsNone(reprint_identity.classify_match("スタートデッキ 麦わらの一味"))

    def test_one_card_code_across_two_products_does_not_collapse_them(self):
        """The products stay distinct identities even though the card code is
        identical - the whole reason product identity is a row, not a prefix."""
        st01 = self._product(1, "ST-01", "スタートデッキ 麦わらの一味")
        op03 = self._product(3, "OP-03", "強大な敵")
        a = resolve_release_identity(self.session, self._print(20, st01)).identity
        b = resolve_release_identity(self.session, self._print(21, op03)).identity
        self.assertNotEqual(a.product_id, b.product_id)
        self.assertNotEqual(a.accepted_names(), b.accepted_names())

    # --- G. marketplace contradiction ---------------------------------------

    def test_a_marketplace_label_contradicting_the_product_still_refuses(self):
        """The authoritative product wins. A listing naming a different real
        product is refused, not accepted because the name is well-formed."""
        op03 = self._product(3, "OP-03", "強大な敵")
        identity = resolve_release_identity(self.session, self._print(21, op03)).identity
        self.assertIsNone(identity.classify_match("ブースターパック 頂上決戦"))
        self.assertIsNone(identity.classify_match("プレミアムカードコレクション"))
        self.assertIsNone(identity.classify_match(None))
        self.assertIsNone(identity.classify_match(""))

    # --- H. missing / unusable authoritative identity ------------------------

    def test_a_print_with_no_product_link_is_refused(self):
        result = resolve_release_identity(self.session, self._print(30, None))
        self.assertIsNone(result.identity)
        self.assertTrue(
            any(r.startswith("authoritative_release_identity_missing:") for r in result.refusals),
            result.refusals,
        )

    def test_a_missing_product_row_is_refused(self):
        orphan = CardPrint(
            id=31, canonical_card_id=1, language="jp", release_product_id=9999,
            artwork_key="k31", verification_status="verified", is_active=True,
        )
        self.session.add(orphan)
        self.session.flush()
        result = resolve_release_identity(self.session, orphan)
        self.assertIsNone(result.identity)
        self.assertTrue(any(r.startswith("release_product_row_missing:") for r in result.refusals))

    def test_an_unverified_product_is_refused(self):
        """An unverified product's name is not yet an authority, so it cannot
        be the expectation a listing is measured against."""
        product = self._product(4, "OP-09", "新章", verification_status="unverified")
        result = resolve_release_identity(self.session, self._print(32, product))
        self.assertIsNone(result.identity)
        self.assertTrue(any(r.startswith("release_product_unverified:") for r in result.refusals))

    def test_a_missing_print_is_refused(self):
        result = resolve_release_identity(self.session, None)
        self.assertIsNone(result.identity)
        self.assertEqual(result.refusals, ("card_print_missing_for_release_identity",))

    # --- the three Japanese renderings added 2026-08-31 ----------------------

    def test_the_japanese_storefront_renderings_resolve_their_products(self):
        """The nine canary mappings that failed `release_name_mismatch`.

        Each product is given the storefront spelling observed on SNKRDUNK's
        JAPANESE page, as a `source_rendering` alias, and the release name the
        page displayed must then resolve - reported as a source rendering, not
        as a Bandai attestation.
        """
        cases = [
            ("スタンダードバトルパック2022 Vol.1", "スタンダードバトルパックVol.1"),
            ("スタンダードバトルパック2022 Vol.2", "スタンダードバトルパックVol.2"),
            ("1st ANNIVERSARY SET", "1st アニバーサリーセット"),
        ]
        for index, (bandai_name, storefront) in enumerate(cases, start=40):
            with self.subTest(product=bandai_name):
                product = self._product(index, None, bandai_name)
                self._alias(product, storefront, "source_rendering")
                identity = resolve_release_identity(
                    self.session, self._print(500 + index, product)
                ).identity
                # Bandai's own name still answers as Bandai...
                self.assertEqual(
                    identity.classify_match(bandai_name), MATCH_BANDAI_OFFICIAL
                )
                # ...and the storefront spelling answers as a rendering.
                self.assertEqual(
                    identity.classify_match(storefront), MATCH_SOURCE_RENDERING
                )

    def test_a_storefront_rendering_does_not_leak_to_a_neighbouring_product(self):
        """Vol.3 is the dangerous neighbour: Bandai drops the year from its
        name, so its prose is the closest to the Vol.1/Vol.2 spellings. It must
        not accept them, and they must not accept its."""
        vol1 = self._product(60, None, "スタンダードバトルパック2022 Vol.1")
        self._alias(vol1, "スタンダードバトルパックVol.1", "source_rendering")
        vol3 = self._product(61, None, "スタンダードバトルパック Vol.3")

        id1 = resolve_release_identity(self.session, self._print(560, vol1)).identity
        id3 = resolve_release_identity(self.session, self._print(561, vol3)).identity

        self.assertIsNone(id1.classify_match("スタンダードバトルパックVol.3"))
        self.assertIsNone(id3.classify_match("スタンダードバトルパックVol.1"))
        # Vol.3's own name still resolves for Vol.3.
        self.assertIsNotNone(id3.classify_match("スタンダードバトルパックVol.3"))

    # --- authority separation ------------------------------------------------

    def test_a_storefront_spelling_is_never_reported_as_a_bandai_name(self):
        product = self._product(5, "OP-05", "新時代の主役")
        self._alias(product, "新時代の主役だよ", "source_rendering")
        self._alias(product, "ブースターパック 新時代の主役", "bandai_additional")
        identity = resolve_release_identity(self.session, self._print(33, product)).identity
        self.assertEqual(identity.classify_match("新時代の主役だよ"), MATCH_SOURCE_RENDERING)
        self.assertEqual(
            identity.classify_match("ブースターパック 新時代の主役"), MATCH_BANDAI_OFFICIAL
        )


if __name__ == "__main__":
    unittest.main()
