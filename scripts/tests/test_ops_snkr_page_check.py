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

    def test_registered_read_runbook(self):
        self.assertEqual(run.RUNBOOKS["snkr-page-check"][:2], ("read", False))


if __name__ == "__main__":
    unittest.main()
