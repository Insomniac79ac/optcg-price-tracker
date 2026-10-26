"""catalogue-import (scripts/ops/catalogue_import.py): scope, capture, plan digest, target, apply gate.

Offline: Bandai is a fake fetcher serving pages shaped like the real Card List, and the importer
is a stand-in that records its argv and calls on_plan the way the real one does.
"""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ops import catalogue_import as ci, common, run  # noqa: E402

PICKER = """
<select id="series">
  <option value="">Select</option>
  <option value="550101">ROMANCE DAWN【OP-01】</option>
  <option value="550205">Heroines vol.2【EB-05】</option>
  <option value="550701">ファミリーデッキセット</option>
  <option value="13000">13000</option>
</select>
"""


def entry(code, image, products):
    info = "<br>".join(products + ["<a href='/cardlist/'>カードリスト</a>", "<a href='/products/'>商品情報</a>"])
    return f"""
<dl class="modalCol" id="{code}">
  <dt><div class="infoCol"><span>{code}</span> | <span>C</span> | <span>CHARACTER</span></div>
  <div class="cardName">Name {code}</div></dt>
  <dd><div class="frontCol"><img class="lazy" src="/d.gif" data-src="../images/cardlist/card/{image}.png?1"></div>
  <div class="backCol"><div class="getInfo"><h3>入手情報</h3>{info}</div></div></dd>
</dl>"""


PAGES = {
    "550101": PICKER + entry("OP01-001", "OP01-001", ["ROMANCE DAWN【OP-01】"]),
    "550205": PICKER + entry("EB05-001", "EB05-001", ["Heroines vol.2【EB-05】"])
    + entry("EB05-002", "EB05-002", ["Heroines vol.2【EB-05】"]),
    "550701": PICKER + entry("FD01-001", "FD01-001", ["ファミリーデッキセット"]),
}


ASIA_PICKER = """<select id="series"><option value="569101">-ROMANCE DAWN- [OP-01]</option>
<option value="569901">Promotion card</option></select>"""
ASIA_EN = {
    "": ASIA_PICKER,
    "569901": ASIA_PICKER + """
<dl class="modalCol" id="P-001"><dt><div class="infoCol"><span>P-001</span> | <span>P</span> | <span>LEADER</span></div>
<div class="cardName">Luffy</div></dt><dd><div class="frontCol"><img data-src="../images/cardlist/card/P-001.png"></div>
<div class="backCol"><div class="getInfo"><h3>Card Set(s)</h3>Promotion Pack Vol.1</div></div></dd></dl>""",
}


class FakeFetcher:
    def __init__(self):
        self.urls = []
        self.requests = 0
        self.retried = 0

    def get(self, url):
        self.urls.append(url)
        self.requests += 1
        if url.startswith(ci.ASIA_EN_CARD_LIST):
            return 200, ASIA_EN.get(url.rsplit("series=", 1)[-1] if "series=" in url else "", ASIA_EN[""]).encode(), "text/html"
        if "series=" in url:
            sid = url.rsplit("series=", 1)[1]
            return (200, PAGES[sid].encode(), "text/html") if sid in PAGES else (200, PICKER.encode(), "text/html")
        return 200, b"\x89PNG" + url.encode(), "image/png"


SCOPES = {"eb-05": {"series": ["550205"], "uncoded_products": []},
          "measure": {"uncoded_series": ["550701"], "exclude_products": ["Gone"], "asia_en_measure": True},
          "family-deck-set": {"series": [], "uncoded_products": ["ファミリーデッキセット"]},
          "bad": {"series": ["5502"], "uncoded_products": []}}


def fake_plan(codes, name="Name"):
    def planned(code):
        doc = {"entry_id": code, "card_code": code, "outcome": "create_card_print", "official_product_code": "EB-05",
               "official_product_display_name": "Heroines vol.2【EB-05】", "official_asset_variant": None,
               "official_artwork_sha256": "a" * 64, "official_name": name, "flags": []}
        return SimpleNamespace(entry_id=code, card_code=code, to_dict=lambda: dict(doc))
    prints = [planned(c) for c in codes]
    return SimpleNamespace(prints=prints, counts=lambda: {"create_card_print": len(prints)})


class FakeImporter:
    """Records argv; calls on_plan; mimics the importer's catch-all (raise -> exit 1, nothing written)."""

    def __init__(self, codes=("EB05-001", "EB05-002"), name="Name"):
        self.codes = codes
        self.name = name
        self.calls = []

    def __call__(self, argv, *, open_tunnel, on_plan):
        self.calls.append(argv)
        print("::add-mask::{not-json")
        try:
            on_plan(fake_plan(self.codes, self.name))
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"applied": "--apply" in argv, "card_prints_created": len(self.codes) if "--apply" in argv else 0,
                          "eligible_plans": len(self.codes), "nested": {"a": 1}}, indent=2))
        return 0


class Scope(unittest.TestCase):
    def test_committed_scopes_are_valid(self):
        scopes = ci.load_scopes()
        for name in scopes:
            ci.resolve_scope(name, scopes)
        self.assertEqual(ci.resolve_scope("eb-05", scopes)["series"], ["550205"])

    def test_unknown_missing_and_malformed_scopes_refuse(self):
        for name in ("", "nope", "bad"):
            with self.assertRaises(common.Refused):
                ci.resolve_scope(name, SCOPES)

    def test_scoped_entries_by_series_or_product(self):
        rows = [{"entry_id": "a", "source_series_id": "550205", "product_names": []},
                {"entry_id": "b", "source_series_id": "550901", "product_names": ["X"]},
                {"entry_id": "c", "source_series_id": "550901", "product_names": ["Y"]}]
        scope = {"series": ["550205"], "uncoded_products": ["X"]}
        self.assertEqual(ci.scoped_entry_ids(rows, scope), {"a", "b"})

    def test_registered_as_collector_affecting_write(self):
        self.assertEqual(run.RUNBOOKS["catalogue-import"][:2], ("write", True))


class Capture(unittest.TestCase):
    def test_series_pages_only_six_digit_and_images_only_for_scope(self):
        fetcher = FakeFetcher()
        with tempfile.TemporaryDirectory() as tmp:
            out = ci.capture(Path(tmp) / "bandai_jp" / "current", ci.resolve_scope("eb-05", SCOPES), fetcher=fetcher)
            entries = [json.loads(l) for l in (Path(tmp) / "bandai_jp/current/entries.jsonl").read_text().splitlines()]
        self.assertFalse(any("series=13000" in u for u in fetcher.urls))
        images = [u for u in fetcher.urls if "series=" not in u]
        self.assertEqual(sorted(u.split("/")[-1].split(".")[0] for u in images), ["EB05-001", "EB05-002"])
        self.assertEqual(out["scoped_entries"], 2)
        # the parser drops Bandai's link labels from product names
        self.assertTrue(all(e["product_names"] in (["ROMANCE DAWN【OP-01】"], ["Heroines vol.2【EB-05】"],
                                                   ["ファミリーデッキセット"]) for e in entries))

    def test_scope_series_not_on_bandais_list_refuses(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(common.Refused):
            ci.capture(Path(tmp) / "c", {"name": "x", "series": ["559999"], "uncoded_products": []},
                       fetcher=FakeFetcher())


class Measure(unittest.TestCase):
    def test_uncoded_series_expand_to_their_products_minus_excludes(self):
        rows = [{"entry_id": "a", "source_series_id": "550901", "product_names": ["P1", "P2"]},
                {"entry_id": "b", "source_series_id": "550901", "product_names": ["Gone"]},
                {"entry_id": "c", "source_series_id": "550101", "product_names": ["OP-01"]}]
        scope = {"series": [], "uncoded_products": ["X"], "uncoded_series": ["550901"], "exclude_products": ["Gone"]}
        self.assertEqual(ci.expand_products(rows, scope), ["P1", "P2", "X"])
        self.assertEqual(ci.multi_product_sets(rows, ["P1"]), [["P1 + P2", 1]])

    def test_compact_report_groups_refusals_by_rule(self):
        rows = [{"product": "A", "jp_rules": "pass", "members": 3},
                {"product": "B", "jp_rules": "refused", "rule": "unambiguous_membership",
                 "detail": "1 entr(y/ies) under 'B' name more than one product (e.g. 'P-001' -> ['B', 'C'])"},
                {"product": "D", "jp_rules": "refused", "rule": "internally_consistent",
                 "detail": "card code 'P-106' appears more than once under 'D'"}]
        out = ci.compact_uncoded(rows)
        self.assertEqual(out["pass"], [["A", 3]])
        self.assertEqual(out["refused"], {"unambiguous_membership": [["B", "P-001"]],
                                          "internally_consistent": [["D", "P-106"]]})

    def test_measure_scope_reports_family_deck_exception_and_asia_en_names(self):
        importer = FakeImporter()
        with tempfile.TemporaryDirectory() as tmp:
            out = ci.run(tmp, scope="measure", fetcher=FakeFetcher(), main=importer, open_tunnel=OPEN, scopes=SCOPES)
        self.assertEqual(importer.calls, [])
        self.assertEqual(out["uncoded"]["pass"], [["ファミリーデッキセット", 1, "single_product_catchall"]])
        self.assertEqual(out["exclude_products_not_found"], ["Gone"])
        asia = out["asia_en"]
        self.assertEqual(asia["uncoded_series"], [["569901", "Promotion card"]])
        self.assertEqual(asia["top_values"], [["Promotion Pack Vol.1", 1]])
        self.assertEqual(asia["obtain_block_labels"], [["Card Set(s)", 1]])


class PlanDigest(unittest.TestCase):
    def test_sha_is_stable_and_moves_with_any_print_field(self):
        scope = ci.resolve_scope("eb-05", SCOPES)
        rows = ci.plan_rows(fake_plan(["EB05-002", "EB05-001"]))
        self.assertEqual([r["print"]["card_code"] for r in rows], ["EB05-001", "EB05-002"])
        sha = ci.plan_sha(scope, rows)
        self.assertEqual(sha, ci.plan_sha(scope, ci.plan_rows(fake_plan(["EB05-001", "EB05-002"]))))
        # metadata the applier writes (a corrected name) moves the SHA, not only identity fields
        self.assertNotEqual(sha, ci.plan_sha(scope, ci.plan_rows(fake_plan(["EB05-001", "EB05-002"], name="New"))))
        # so does the entry record the plan was built from
        records = {"EB05-001": {"fields": [{"name": "cost", "value": "3"}]}}
        self.assertNotEqual(sha, ci.plan_sha(scope, ci.plan_rows(fake_plan(["EB05-001", "EB05-002"]), records)))

    def test_apply_needs_the_matching_sha(self):
        with self.assertRaises(common.Refused):
            ci.check_apply("", "a" * 64)
        with self.assertRaises(common.Refused):
            ci.check_apply("b" * 64, "a" * 64)
        ci.check_apply("a" * 64, "a" * 64)


class Target(unittest.TestCase):
    def test_proxy_url_is_quoted_and_every_form_is_registered_as_a_secret(self):
        url = ci.proxy_url(lambda: ({"domain": "h.proxy.rlwy.net", "proxyPort": 1234},
                                    {"PGUSER": "postgres", "PGPASSWORD": "p@ss/wd", "PGDATABASE": "railway"}))
        self.assertEqual(url, "postgresql://postgres:p%40ss%2Fwd@h.proxy.rlwy.net:1234/railway")
        for form in (url, "postgresql+psycopg://postgres:p%40ss%2Fwd@h.proxy.rlwy.net:1234/railway",
                     "p@ss/wd", "p%40ss%2Fwd"):
            self.assertIn(form, common.secret_values())

    def test_report_is_the_last_json_object_even_after_a_brace_in_a_mask_line(self):
        text = "::add-mask::{x\n" + json.dumps({"a": {"b": 1}}, indent=2) + "\n"
        self.assertEqual(ci.parse_report(text), {"a": {"b": 1}})
        self.assertIsNone(ci.parse_report("no json here"))


FRESH = lambda: {"age_hours": 3.0}  # noqa: E731
OPEN = lambda service, environment: "postgresql://u:p@h:1/d"  # noqa: E731
NOON = lambda: __import__("datetime").datetime(2026, 10, 26, 12, tzinfo=__import__("datetime").timezone.utc)  # noqa: E731


class RunFlow(unittest.TestCase):
    def setUp(self):
        sys.modules.setdefault("generate_staging_state", SimpleNamespace(timestamp=lambda: "t"))

    def test_dry_run_plans_the_scope_read_only_and_reports_the_sha(self):
        importer = FakeImporter()
        with tempfile.TemporaryDirectory() as tmp:
            out = ci.run(tmp, scope="eb-05", fetcher=FakeFetcher(), main=importer, open_tunnel=OPEN, scopes=SCOPES)
        argv = importer.calls[0]
        self.assertEqual(argv[argv.index("--series") + 1], "550205")
        self.assertNotIn("--apply", argv)
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["plan_sha256"]), 64)
        self.assertEqual(out["outcomes"], {"create_card_print": 2})

    def test_apply_with_the_dry_run_sha_writes_and_a_different_plan_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            sha = ci.run(tmp, scope="eb-05", fetcher=FakeFetcher(), main=FakeImporter(), open_tunnel=OPEN,
                         scopes=SCOPES)["plan_sha256"]
        importer = FakeImporter()
        with tempfile.TemporaryDirectory() as tmp:
            ok = ci.run(tmp, apply=True, scope="eb-05", expected_sha256=sha, fetcher=FakeFetcher(), main=importer,
                        open_tunnel=OPEN, scopes=SCOPES, backup=FRESH, now=NOON)
        self.assertTrue(ok["ok"])
        self.assertIn("--confirm", importer.calls[0])
        self.assertEqual(ok["report"]["card_prints_created"], 2)
        changed = FakeImporter(codes=("EB05-001",))
        with tempfile.TemporaryDirectory() as tmp:
            refused = ci.run(tmp, apply=True, scope="eb-05", expected_sha256=sha, fetcher=FakeFetcher(), main=changed,
                             open_tunnel=OPEN, scopes=SCOPES, backup=FRESH, now=NOON)
        self.assertFalse(refused["ok"])
        self.assertIn("differs", refused["refused"])
        self.assertIsNone(refused["report"])

    def test_apply_rechecks_the_quiet_window_after_the_capture(self):
        importer = FakeImporter()
        late = lambda: __import__("datetime").datetime(2026, 10, 26, 19, 45, tzinfo=__import__("datetime").timezone.utc)  # noqa: E731
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(common.Refused):
            ci.run(tmp, apply=True, scope="eb-05", expected_sha256="a" * 64, fetcher=FakeFetcher(), main=importer,
                   open_tunnel=OPEN, scopes=SCOPES, backup=FRESH, now=late)
        self.assertEqual(importer.calls, [])

    def test_apply_refuses_without_a_recent_backup_before_any_request(self):
        fetcher = FakeFetcher()
        for stale in (lambda: None, lambda: {"age_hours": 30}):
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(common.Refused):
                ci.run(tmp, apply=True, scope="eb-05", expected_sha256="a" * 64, fetcher=fetcher,
                       main=FakeImporter(), open_tunnel=OPEN, scopes=SCOPES, backup=stale)
        self.assertEqual(fetcher.urls, [])

    def test_uncoded_products_are_reported_with_their_rule_and_never_applied(self):
        importer = FakeImporter()
        with tempfile.TemporaryDirectory() as tmp:
            out = ci.run(tmp, scope="family-deck-set", fetcher=FakeFetcher(), main=importer, open_tunnel=OPEN,
                         scopes=SCOPES)
        self.assertEqual(importer.calls, [])
        # Rule 6's proposed single-product exception is allowed in the report and flagged.
        self.assertEqual(out["uncoded"]["pass"], [["ファミリーデッキセット", 1, "single_product_catchall"]])
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(common.Refused):
            ci.run(tmp, apply=True, scope="family-deck-set", expected_sha256="a" * 64, fetcher=FakeFetcher(),
                   main=importer, open_tunnel=OPEN, scopes=SCOPES)


if __name__ == "__main__":
    unittest.main()
