"""Decision rules of scripts/staging_web_smoke.py (the browser run itself needs the staging site)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import staging_web_smoke as smoke  # noqa: E402

WEB = smoke.WEB


class Redirects(unittest.TestCase):
    def test_sign_in_with_callback(self):
        self.assertTrue(smoke.redirect_ok(WEB + "/sign-in?callbackUrl=%2Faccount", "/account"))
        self.assertTrue(smoke.redirect_ok(WEB + "/sign-in?callbackUrl=/watchlist", "/watchlist"))

    def test_not_redirected_or_wrong_target(self):
        self.assertFalse(smoke.redirect_ok(WEB + "/account", "/account"))
        self.assertFalse(smoke.redirect_ok(WEB + "/sign-in", "/account"))
        self.assertFalse(smoke.redirect_ok(WEB + "/sign-in?callbackUrl=%2Fcollection", "/account"))
        self.assertFalse(smoke.redirect_ok("https://evil.example/sign-in?callbackUrl=%2Faccount", "/account"))
        self.assertFalse(smoke.redirect_ok(WEB + "/admin/login?callbackUrl=%2Faccount", "/account"))


class Images(unittest.TestCase):
    def test_loaded(self):
        self.assertEqual(smoke.image_problems([{"src": "a", "complete": True, "width": 300}], []), [])

    def test_broken_none_or_failed(self):
        self.assertTrue(smoke.image_problems([{"src": "a", "complete": True, "width": 0},
                                              {"src": "b", "complete": True, "width": 9}], []))
        self.assertEqual(smoke.image_problems([], []), ["no card image loaded"])
        self.assertTrue(smoke.image_problems([{"src": "a", "complete": True, "width": 9}], [("u", 404)]))

    def test_routes(self):
        self.assertEqual(set(smoke.PUBLIC), {"/", "/cards", "/prints/5661", "/sign-in"})
        self.assertEqual(set(smoke.SIGNED_OUT), {"/account", "/collection", "/watchlist"})


if __name__ == "__main__":
    unittest.main()
