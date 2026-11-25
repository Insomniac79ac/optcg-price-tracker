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
ASIA_UNNAMED = ASIA_EN["569901"].replace("<h3>Card Set(s)</h3>Promotion Pack Vol.1", "<h3>Card Sets</h3>Promotion Pack Vol.1")


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
          "measure": {"uncoded_series": ["550701"], "exclude_products": ["Gone"], "asia_en_measure": True,
                      "report_only": True},
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

    def test_committed_op18_scope_is_exactly_series_550118(self):
        # Mission 5 (#274): the id Bandai's picker gave (ops-readonly official-series-index run
        # 43379261767), no uncoded product and no other series, so the import cannot widen.
        scope = ci.resolve_scope("op-18", ci.load_scopes())
        self.assertEqual(scope["series"], ["550118"])
        self.assertFalse(scope.get("uncoded_products"))
        self.assertFalse(scope.get("uncoded_series"))
        self.assertFalse(scope.get("report_only"))

    def test_committed_op18_scope_excludes_exactly_the_two_conflicts(self):
        # Owner t642u (2026-11-24, option A): OP18-064_p1 and OP18-084_p2 stay out until option D.
        scope = ci.resolve_scope("op-18", ci.load_scopes())
        self.assertEqual(sorted(ci.excluded_ids(scope)), ["OP18-064_p1", "OP18-084_p2"])
        self.assertTrue(all(e["reason"] for e in scope["exclude_entry_ids"]))

    def test_malformed_exclude_entry_ids_refuse(self):
        for bad in ([{"entry_id": "a"}], [{"entry_id": "a", "reason": ""}], ["a"],
                    [{"entry_id": "a", "reason": "r"}, {"entry_id": "a", "reason": "s"}],
                    [{"entry_id": " a", "reason": "r"}], {"entry_id": "a", "reason": "r"}):
            with self.assertRaises(common.Refused):
                ci.resolve_scope("x", {"x": {"series": ["550205"], "exclude_entry_ids": bad}})

    def test_excluded_entries_get_no_image_and_are_reported_by_id(self):
        rows = [{"entry_id": "a", "card_code": "A", "rarity": "UC", "source_series_id": "550205", "product_names": []},
                {"entry_id": "a_p1", "card_code": "A", "rarity": "TR", "source_series_id": "550205", "product_names": []}]
        scope = ci.resolve_scope("x", {"x": {"series": ["550205"],
                                             "exclude_entry_ids": [{"entry_id": "a_p1", "reason": "conflict"}]}})
        self.assertEqual(ci.scoped_entry_ids(rows, scope), {"a"})
        self.assertEqual(ci.excluded_report(rows, scope),
                         [{"entry_id": "a_p1", "card_code": "A", "rarity": "TR", "reason": "conflict"}])
        stale = ci.resolve_scope("x", {"x": {"series": ["550205"],
                                             "exclude_entry_ids": [{"entry_id": "gone", "reason": "r"}]}})
        with self.assertRaises(common.Refused):
            ci.excluded_report(rows, stale)

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
        rows = [{"product": "A", "jp_rules": "pass", "members": 3, "jp_only": False},
                {"product": "J", "jp_rules": "pass", "members": 1, "jp_only": True, "repeated_card_codes": ["P-106"]},
                {"product": "B", "jp_rules": "refused", "rule": "asia_en_disagrees",
                 "detail": "bandai_asia_en product 'Pack EN' shares 2 of this product's 3 card code(s) but has 4"},
                {"product": "D", "jp_rules": "refused", "rule": "internally_consistent",
                 "detail": "card code 'P-106' appears more than once under 'D' with the same entry"}]
        out = ci.compact_uncoded(rows)
        self.assertEqual((out["pass"], out["asia_en_agrees"], out["japan_only"]), (2, 1, [["J", 1]]))
        self.assertEqual(out["flagged"], [["J", 1, "repeated:P-106"]])
        self.assertEqual(out["refused"], {"asia_en_disagrees": [["B", "Pack EN"]],
                                          "internally_consistent": [["D", "P-106"]]})

    def test_family_batches_select_by_pattern(self):
        rows = [{"entry_id": "a", "source_series_id": "550901", "product_names": ["フラッグシップバトル2022 優勝記念品"]},
                {"entry_id": "b", "source_series_id": "550901", "product_names": ["交流会3月開催記念品"]}]
        scopes = {"fb": {"uncoded_series": ["550901"], "product_pattern": "フラッグシップ"},
                  "rest": {"uncoded_series": ["550901"], "exclude_pattern": "フラッグシップ"}}
        self.assertEqual(ci.expand_products(rows, ci.resolve_scope("fb", scopes)), ["フラッグシップバトル2022 優勝記念品"])
        self.assertEqual(ci.expand_products(rows, ci.resolve_scope("rest", scopes)), ["交流会3月開催記念品"])
        with self.assertRaises(common.Refused):
            ci.resolve_scope("bad", {"bad": {"uncoded_series": ["550901"], "product_pattern": "("}})

    def test_committed_family_batches_partition_the_products(self):
        scopes = ci.load_scopes()
        batches = [ci.resolve_scope(n, scopes) for n in ("flagship-battle", "standard-battle", "promotion-packs",
                                                          "premium-card-collections", "magazines", "events-and-prizes",
                                                          "other-limited")]
        names = [["フラッグシップバトル2022 優勝記念品"], ["スタンダードバトルパックVol.4"], ["プロモーションパックVol.8"],
                 ["プレミアムカードコレクション-ウタ-", "プレミアムカードコレクション-ONE PIECE DAY’25-",
                  "プレミアムカードコレクション-メラメラの実争奪戦Edition-"],
                 ["Vジャンプ9月特大号付録（2022年7月21日売）"], ["メラメラの実争奪戦 上位記念品", "交流会3月開催記念品"],
                 ["1st ANNIVERSARY SET"]]
        flat = [n for group in names for n in group]
        rows = [{"entry_id": str(i), "source_series_id": "550901", "product_names": [n]} for i, n in enumerate(
            flat + ["ONE PIECE カードゲーム China 3rd ANNIVERSARY SET", "ONE PIECE カードゲーム English 3rd ANNIVERSARY SET"])]
        picked = [ci.expand_products(rows, b) for b in batches]
        self.assertEqual(picked, [sorted(g) for g in names])  # each once; a future China/English set in none

    def test_measure_scope_reports_and_never_imports(self):
        importer = FakeImporter()
        with tempfile.TemporaryDirectory() as tmp:
            out = ci.run(tmp, scope="measure", fetcher=FakeFetcher(), main=importer, open_tunnel=OPEN, scopes=SCOPES)
            with self.assertRaises(common.Refused):
                ci.run(tmp, apply=True, scope="measure", expected_sha256="a" * 64, fetcher=FakeFetcher(),
                       main=importer, open_tunnel=OPEN, scopes=SCOPES, backup=FRESH, now=NOON)
        self.assertEqual(importer.calls, [])
        self.assertEqual(out["uncoded"]["flagged"], [["ファミリーデッキセット", 1, "single_product_catchall"]])
        self.assertEqual(out["uncoded"]["japan_only"], [["ファミリーデッキセット", 1]])  # FD codes not on Asia-EN
        self.assertEqual(out["exclude_products_not_found"], ["Gone"])
        asia = out["asia_en"]
        self.assertEqual(asia["pages"], [["569901", "Promotion card", 1]])
        self.assertEqual(asia["top_products"], [["Promotion Pack Vol.1", 1]])
        self.assertEqual(asia["obtain_block_labels"], [["Card Set(s)", 1]])

    def test_an_asia_en_page_that_reads_no_products_refuses(self):
        class Relabelled(FakeFetcher):
            def get(self, url):
                if url.endswith("series=569901"):
                    self.urls.append(url)
                    return 200, ASIA_UNNAMED.encode(), "text/html"
                return super().get(url)
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(common.Refused):
            ci.run(tmp, scope="family-deck-set", fetcher=Relabelled(), main=FakeImporter(), open_tunnel=OPEN, scopes=SCOPES)

    def test_an_asia_en_page_that_fails_refuses_rather_than_reading_absent(self):
        class Broken(FakeFetcher):
            def get(self, url):
                if url.endswith("series=569901"):
                    self.urls.append(url)
                    return 500, b"", None
                return super().get(url)
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(common.Refused):
            ci.run(tmp, scope="family-deck-set", fetcher=Broken(), main=FakeImporter(), open_tunnel=OPEN, scopes=SCOPES)


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

    def test_exclusions_are_in_the_sha_only_for_scopes_that_exclude(self):
        rows = ci.plan_rows(fake_plan(["EB05-001"]))
        plain = ci.resolve_scope("eb-05", SCOPES)
        self.assertEqual(ci.plan_sha(plain, rows), ci.plan_sha(dict(plain, exclude_entry_ids=[]), rows))
        one = dict(plain, exclude_entry_ids=[{"entry_id": "EB05-002", "reason": "r"}])
        two = dict(plain, exclude_entry_ids=[{"entry_id": "EB05-003", "reason": "r"}])
        self.assertNotEqual(ci.plan_sha(plain, rows), ci.plan_sha(one, rows))
        self.assertNotEqual(ci.plan_sha(one, rows), ci.plan_sha(two, rows))

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

    def test_a_proven_uncoded_product_is_planned_and_its_evidence_is_in_the_sha(self):
        importer = FakeImporter()
        with tempfile.TemporaryDirectory() as tmp:
            out = ci.run(tmp, scope="family-deck-set", fetcher=FakeFetcher(), main=importer, open_tunnel=OPEN,
                         scopes=SCOPES)
        argv = importer.calls[0]
        self.assertEqual(argv[argv.index("--uncoded-product") + 1], "ファミリーデッキセット")
        self.assertNotIn("--series", argv)
        self.assertTrue(out["ok"])
        scope = ci.resolve_scope("family-deck-set", SCOPES)
        rows = ci.plan_rows(fake_plan(["EB05-001", "EB05-002"]))
        self.assertNotEqual(ci.plan_sha(scope, rows), ci.plan_sha(scope, rows, ["ファミリーデッキセット"], "x"))
        self.assertNotEqual(ci.plan_sha(scope, rows, ["ファミリーデッキセット"], "x"),
                            ci.plan_sha(scope, rows, ["ファミリーデッキセット"], "y"))


if __name__ == "__main__":
    unittest.main()


class FakeImporterModule:
    """Shaped like app.import_frozen_bandai_to_canonical_staging: main() measures nothing itself and
    hands the scoped entries to the module-level plan_entries, then calls on_plan."""

    def __init__(self, codes):
        self.codes = codes
        self.seen = []

    def plan_entries(self, session, entries, **kwargs):
        self.seen.append([e.entry_id for e in entries])
        return fake_plan([e.entry_id for e in entries])

    def main(self, argv, *, open_tunnel, on_plan):
        entries = [SimpleNamespace(entry_id=c) for c in self.codes]
        try:
            plan = self.plan_entries(None, entries, sibling_counts={})   # an instance attribute wins, as a module global
            on_plan(plan)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"applied": "--apply" in argv, "eligible_plans": len(plan.prints)}))
        return 0


class ExcludedEntries(unittest.TestCase):
    """Owner t642u (2026-11-24): OP-18 option A leaves the 2 conflicting parallels out, and the dry
    run prints every excluded entry by id."""

    SCOPES = {"eb-05x": {"series": ["550205"], "uncoded_products": [],
                         "exclude_entry_ids": [{"entry_id": "EB05-002", "reason": "planner conflict"}]}}

    def setUp(self):
        sys.modules.setdefault("generate_staging_state", SimpleNamespace(timestamp=lambda: "t"))

    def test_dry_run_plans_without_the_excluded_entry_and_prints_it(self):
        module = FakeImporterModule(["EB05-001", "EB05-002"])
        with tempfile.TemporaryDirectory() as tmp:
            out = ci.run(tmp, scope="eb-05x", fetcher=FakeFetcher(), main=module.main, open_tunnel=OPEN,
                         scopes=self.SCOPES, importer_module=module)
        self.assertTrue(out["ok"], out)
        self.assertEqual(module.seen, [["EB05-001"]])
        self.assertEqual(out["excluded_entries"],
                         [{"entry_id": "EB05-002", "card_code": "EB05-002", "rarity": "C", "reason": "planner conflict"}])
        self.assertEqual(out["excluded_at_planner"], ["EB05-002"])
        self.assertEqual(out["outcomes"], {"create_card_print": 1})
        self.assertEqual(out["capture"]["scoped_entries"], 1)
        self.assertIs(module.plan_entries.__func__, FakeImporterModule.plan_entries)   # restored after the run

    def test_a_plan_that_still_holds_an_excluded_entry_refuses(self):
        importer = FakeImporter(codes=("EB05-001", "EB05-002"))   # ignores the planner filter
        module = SimpleNamespace(plan_entries=lambda *a, **k: None)
        with tempfile.TemporaryDirectory() as tmp:
            out = ci.run(tmp, scope="eb-05x", fetcher=FakeFetcher(), main=importer, open_tunnel=OPEN,
                         scopes=self.SCOPES, importer_module=module)
        self.assertFalse(out["ok"])
        self.assertIn("EB05-002", out["refused"])

    def test_the_real_importer_hands_entries_to_plan_entries_second(self):
        import inspect
        from app import import_frozen_bandai_to_canonical_staging as importer
        self.assertEqual(list(inspect.signature(importer.plan_entries).parameters)[:2], ["session", "entries"])
        self.assertIn("plan_entries(", inspect.getsource(importer.main))


TRANSITION = {"canonical_card_id": 7977, "card_code": "EB05-001", "old_rarity": "UC", "own_set": "EB05",
              "own_set_rarities": ["TR", "UC"]}
DIFFERENCE = {"card_code": "EB05-001", "canonical_card_id": 7977, "canonical_rarity": "UC", "own_set": "EB05",
              "own_set_rarities": ["TR", "UC"]}


def transition_plan(codes=("EB05-001", "EB05-002"), differences=(DIFFERENCE,)):
    plan = fake_plan(codes)
    first = plan.prints[0]
    doc = dict(first.to_dict(), canonical_rarity_transition=dict(TRANSITION))
    plan.prints[0] = SimpleNamespace(entry_id=first.entry_id, card_code=first.card_code, to_dict=lambda: dict(doc))
    plan.same_set_rarity_differences = [dict(d) for d in differences]
    return plan


class TransitionImporter(FakeImporter):
    """Like FakeImporter, but its plan carries one canonical rarity transition and the early
    warning, and its report carries the applier's per-print C1/C2 list."""

    def __call__(self, argv, *, open_tunnel, on_plan):
        self.calls.append(argv)
        on_plan(transition_plan(self.codes))
        prints = [{"card_print_id": 7103, "is_active": True, "official_rarity": "UC",
                   "effective_rarity_before": "UC", "effective_rarity_after": "UC"}]
        print(json.dumps({"applied": False, "canonical_rarity_transitions": [dict(TRANSITION, prints=prints)],
                          "canonical_rarity_transitions_applied": 0}))
        return 0


class CanonicalRarityTransitionReport(unittest.TestCase):
    """Owner t648u: the dry run lists each transition and every print's rarity before and after,
    and prints the early-warning list on every run; both sit inside plan_sha256."""

    def setUp(self):
        sys.modules.setdefault("generate_staging_state", SimpleNamespace(timestamp=lambda: "t"))

    def test_transitions_are_read_from_the_plan_rows_one_per_card(self):
        rows = ci.plan_rows(transition_plan())
        self.assertEqual(ci.rarity_transitions(rows), [dict(TRANSITION, new_rarity=None, entry_id="EB05-001")])
        self.assertEqual(ci.rarity_transitions(ci.plan_rows(fake_plan(["EB05-001"]))), [])

    def test_a_transition_moves_the_sha(self):
        scope = ci.resolve_scope("eb-05", SCOPES)
        plain = ci.plan_sha(scope, ci.plan_rows(fake_plan(["EB05-001", "EB05-002"])))
        self.assertNotEqual(plain, ci.plan_sha(scope, ci.plan_rows(transition_plan())))

    def test_the_early_warning_is_in_the_sha_only_when_present(self):
        scope = ci.resolve_scope("eb-05", SCOPES)
        rows = ci.plan_rows(fake_plan(["EB05-001"]))
        self.assertEqual(ci.plan_sha(scope, rows), ci.plan_sha(scope, rows, same_set_rarity_differences=[]))
        self.assertNotEqual(ci.plan_sha(scope, rows), ci.plan_sha(scope, rows, same_set_rarity_differences=[DIFFERENCE]))

    def test_every_dry_run_prints_the_early_warning_even_when_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = ci.run(tmp, scope="eb-05", fetcher=FakeFetcher(), main=FakeImporter(), open_tunnel=OPEN, scopes=SCOPES)
        self.assertEqual(out["same_set_rarity_differences"], [])
        self.assertEqual(out["canonical_rarity_transitions"], [])
        self.assertNotIn("canonical_rarity_transition_prints", out)

    def test_dry_run_lists_the_transition_its_prints_and_the_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = ci.run(tmp, scope="eb-05", fetcher=FakeFetcher(), main=TransitionImporter(), open_tunnel=OPEN,
                         scopes=SCOPES)
        self.assertTrue(out["ok"])
        self.assertEqual(out["canonical_rarity_transitions"][0]["canonical_card_id"], 7977)
        self.assertEqual(out["canonical_rarity_transitions"][0]["new_rarity"], None)
        prints = out["canonical_rarity_transition_prints"][0]["prints"]
        self.assertEqual([(p["effective_rarity_before"], p["effective_rarity_after"]) for p in prints], [("UC", "UC")])
        self.assertEqual(out["same_set_rarity_differences"], [DIFFERENCE])
        self.assertEqual(out["report"]["canonical_rarity_transitions_applied"], 0)
        with tempfile.TemporaryDirectory() as tmp:
            plain = ci.run(tmp, scope="eb-05", fetcher=FakeFetcher(), main=FakeImporter(), open_tunnel=OPEN,
                           scopes=SCOPES)
        self.assertNotEqual(out["plan_sha256"], plain["plan_sha256"])
