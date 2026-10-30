"""snkr-page-check (scripts/ops/snkr_page_check.py): decoding stored pages and describing their images."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ops import run, snkr_page_check as spc  # noqa: E402

OLD = '<div><img class="Gallery_x__mainImage" src="/img/a.webp?1"><img class="Thumb_y"></div>'
NEW = '<div><img class="Carousel_x__slideImage" src="/img/a.webp"><img class="Carousel_x__slideImage"></div>'


class FakeConn:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params):
        row = self.rows.get(params[0])

        class R:
            def fetchone(self_inner):
                return row
        return R()


class Describe(unittest.TestCase):
    def test_counts_main_image_imgs_and_image_classes(self):
        old, new = spc.describe(OLD), spc.describe(NEW)
        self.assertEqual((old["main_image_imgs"], old["main_image_srcs"]), (1, ["/img/a.webp"]))
        self.assertEqual(new["main_image_imgs"], 0)
        self.assertIn(["img.Carousel_x__slideImage", 2], [list(t) for t in new["image_class_tokens"]])

    def test_decodes_a_dictionary_encoded_page_through_its_base(self):
        from opcg_source_identity.raw_payload import encode, sha256

        base, body = OLD * 50, (OLD * 49 + NEW)
        stored = encode(body.encode(), base_id=7, base_body=base.encode())
        rows = {7: {"raw_content": base, "content_hash": sha256(base.encode()), "http_status": 200},
                9: {"raw_content": stored, "content_hash": sha256(body.encode()), "http_status": 200}}
        snap, text = spc.load_text(FakeConn(rows), 9)
        self.assertEqual(text, body)

    def test_parse_trace_runs_the_collector_parser_offline(self):
        fixture = (ROOT / "services/snkrdunk_collector/tests/fixtures/product_page_reduced.html").read_text()
        trace = spc.parse_trace(fixture)
        self.assertEqual((trace["raw_floor_jpy"], trace["chip_container"]), (29000, True))
        self.assertEqual(trace["raw_conditions"], ["A", "B", "C", "D"])
        self.assertTrue(trace["image"].endswith("20221121015111-0.webp?size=l"))
        self.assertIn("出品待ち", trace["chip_excerpt"])
        self.assertTrue(any("__price" in t for t, _ in trace["price_class_tokens"]))
        self.assertEqual(trace["gallery"]["gallery_elements"], 0)
        self.assertIn("expected exactly one gallery element", trace["gallery"]["stopped_at"])

    def test_gallery_trace_follows_the_retained_gallery_recovery(self):
        import json
        from bs4 import BeautifulSoup

        url = "https://cdn.snkrdunk.com/upload_bg_removed/88e7414d-449b-4ce5-bf15-b61311fc8865.webp"
        props = {"mainImages": [{"src": url}], "variantSources": [{"productId": 1, "imageUrl": url}]}
        payload = "71:I" + json.dumps([1, ["c.js"], "ApparelGalleryContainer"]) + "\n43:" + \
            json.dumps(["$", "$L71", None, props]) + "\n"
        page = '<img class="slWKSa_mainImage" src="/_next/static/media/no-image.x.webp">' \
               '<script>self.__next_f.push(' + json.dumps([1, payload]) + ')</script>'
        trace = spc.gallery_trace(BeautifulSoup(page, "html.parser"))
        self.assertEqual((trace["stopped_at"], trace["recovered"], trace["main_images"]), (None, True, 1))
        self.assertEqual(trace["main_image_src_shape"]["host"], "cdn.snkrdunk.com")
        ref_payload = '8d:"ApparelGalleryContainer"\n8e:I' + json.dumps([213805, ["c.js"], "$8d"]) + \
            "\n43:" + json.dumps(["$", "$L8e", None, props]) + "\n"
        ref_page = '<script>self.__next_f.push(' + json.dumps([1, ref_payload]) + ')</script>'
        ref = spc.gallery_trace(BeautifulSoup(ref_page, "html.parser"))
        self.assertEqual((ref["gallery_modules"], ref["module_names_by_reference"], ref["gallery_elements"]),
                         (["$L8e"], 1, 1))
        self.assertIn("mainImages", ref["gallery_props_excerpt"])
        dup = page.replace(json.dumps([1, payload]), json.dumps([1, payload + payload]))
        self.assertIn("repeated Flight record key", spc.gallery_trace(BeautifulSoup(dup, "html.parser"))["stopped_at"])

    def test_price_trace_reports_where_prices_live_and_loading_markers(self):
        import json
        from bs4 import BeautifulSoup

        data = {"conditions": [{"label": "A", "minPrice": 2900, "priceText": "¥2,900"}],
                "listingCount": 3}
        payload = "5:" + json.dumps(data, ensure_ascii=False) + "\n"
        page = ('<div class="x_wrap x_skeleton"><div class="c_box">'
                '<button class="c_chip"><p class="c_variant">A</p><p class="c_awaiting">出品待ち</p></button>'
                '<button class="c_chip"><p class="c_variant">B</p><p class="c_awaiting">出品待ち</p></button>'
                '</div></div><a href="https://snkrdunk.com/v1/apparels/123/sizes">x</a>'
                '<script>self.__next_f.push(' + json.dumps([1, payload], ensure_ascii=False) + ')</script>')
        trace = spc.price_trace(BeautifulSoup(page, "html.parser"), page)
        keys = dict(trace["payload_price_keys"])
        self.assertEqual((keys["minPrice"], keys["priceText"], keys["listingCount"]), (1, 1, 1))
        self.assertEqual((trace["payload_yen_amounts"], trace["chips"]), (1, ["A | 出品待ち", "B | 出品待ち"]))
        self.assertIn("https://snkrdunk.com/v1/apparels/123/sizes", trace["api_paths"])
        self.assertIn(("x_skeleton", 1), trace["around_chips_loading_markers"])

    def test_registered_read_runbook(self):
        self.assertEqual(run.RUNBOOKS["snkr-page-check"][:2], ("read", False))


if __name__ == "__main__":
    unittest.main()
