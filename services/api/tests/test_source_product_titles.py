"""Title grammars, listing identity and grade keys for the new sources (plan §2.1, §2.3)."""

import pytest

from app.source_products import cardrush_rules, dorasuta_rules, grade_keys
from app.source_products.listing_identity import NotAListing, canonical_listing_identity


# MEASURED titles from the Dorasuta survey (SV §2.1).
@pytest.mark.parametrize(
    "title, code, rarity, markers, kind",
    [
        ("モンキー・D・ルフィ(SEC★/パラレル)(OP05-119)", "OP05-119", "SEC", ("★", "パラレル"), "parallel"),
        ("シャンクス(SP/SR/金箔)(OP09-004)【3周年SP】", "OP09-004", "SR", ("SP", "金箔", "【3周年SP】"), "special"),
        ("ゴール・D・ロジャー(★SEC/ゴールドスーパーパラレル)(OP09-118)", "OP09-118", "SEC",
         ("★", "ゴールドスーパーパラレル"), "parallel"),
        ("ナミ(R)(OP01-016)", "OP01-016", "R", (), "plain"),
        ("ルフィ(TR)(OP05-119)", "OP05-119", "TR", (), "special"),
        ("ゾロ(L/ラメフォイル)(PRB01-001)", "PRB01-001", "L", ("ラメフォイル",), "foil"),
        ("ゾロ(L/WANTED)(OP01-001)", "OP01-001", "L", ("WANTED",), "unknown"),
    ],
)
def test_dorasuta_titles(title, code, rarity, markers, kind):
    parsed = dorasuta_rules.parse_title(title)
    assert (parsed.card_code, parsed.rarity, parsed.markers, parsed.kind) == (code, rarity, markers, kind)


def test_dorasuta_name_and_missing_code():
    assert dorasuta_rules.parse_title("ナミ(R)(OP01-016)").name == "ナミ"
    parsed = dorasuta_rules.parse_title("ワンピースカード ブースターBOX")
    assert parsed.card_code is None and parsed.kind == "unknown"
    assert dorasuta_rules.parse_title("PSA10 ルフィ").kind == "graded"


def test_dorasuta_condition_rows():
    assert dorasuta_rules.grade_key_for_condition("状態A") == "raw:A"
    assert dorasuta_rules.grade_key_for_condition("状態A特価") == "raw:damaged"
    assert dorasuta_rules.grade_key_for_condition(" 状態C(プレイ用) ") == "raw:play"
    assert dorasuta_rules.grade_key_for_condition("未開封") is None


# MEASURED grammar from the CardRush plan (CR §1.3).
@pytest.mark.parametrize(
    "title, code, rarity, kind, grade_key, on_sale, qualifier",
    [
        ("ロロノア・ゾロ【L】{OP01-001}", "OP01-001", "L", "plain", "raw:A", False, None),
        ("〔状態B〕ロロノア・ゾロ【L】{OP01-001}", "OP01-001", "L", "plain", "raw:B", False, None),
        ("〔状態A-〕ナミ【R】{OP01-016}", "OP01-016", "R", "plain", "raw:A-", False, None),
        ("☆SALE☆ナミ(パラレル)【R/P】{OP01-016}", "OP01-016", "R", "parallel", "raw:A", True, None),
        ("〔PSA10鑑定済〕シャンクス【SEC】{OP01-120}", "OP01-120", "SEC", "graded", "graded:PSA:10", False, None),
        ("〔※状態難/PSA10鑑定済〕シャンクス【SEC】{OP01-120}", "OP01-120", "SEC", "graded",
         "graded:PSA:10:flawed", False, None),
        ("(赤白版)ルフィ【P】{P-001}", "P-001", "P", "unknown", "raw:A", False, "赤白版"),
        ("ドン!!カード【-】{-}", None, None, "plain", "raw:A", False, None),
        ("ヤマト(海賊旗フォイル)【SR】{PRB01-011}", "PRB01-011", "SR", "foil", "raw:A", False, None),
        ("〔謎ラベル〕ナミ【R】{OP01-016}", "OP01-016", "R", "plain", None, False, None),
    ],
)
def test_cardrush_titles(title, code, rarity, kind, grade_key, on_sale, qualifier):
    parsed = cardrush_rules.parse_title(title)
    assert (parsed.card_code, parsed.rarity, parsed.kind, parsed.grade_key, parsed.on_sale, parsed.qualifier) == (
        code, rarity, kind, grade_key, on_sale, qualifier,
    )


def test_foil_is_never_plain():
    for title in ("ゾロ(L/ラメフォイル)(PRB01-001)", "ヤマト(SR/海賊旗フォイル)(PRB01-011)"):
        assert dorasuta_rules.parse_title(title).kind == "foil"


@pytest.mark.parametrize(
    "url, identity",
    [
        ("https://dorasuta.jp/onepiece/product?pid=123456", "dorasuta:123456"),
        ("https://www.dorasuta.jp/onepiece/product?pid=0042&utm=x", "dorasuta:42"),
        ("https://www.cardrush-op.jp/product/9876", "cardrush:9876"),
        ("http://cardrush-op.jp/product/9876/", "cardrush:9876"),
    ],
)
def test_listing_identity_vectors(url, identity):
    assert canonical_listing_identity(url) == identity


@pytest.mark.parametrize(
    "url",
    [
        "https://dorasuta.jp/onepiece/product-list?sid=1",
        "https://dorasuta.jp/onepiece/product?pid=1&pid=2",
        "https://dorasuta.jp/onepiece/product?pid=abc",
        "https://www.cardrush-op.jp/product-group/42",
        "https://www.cardrush-op.jp/product/12/reviews",
        "https://evil.example/product/1",
        "ftp://www.cardrush-op.jp/product/1",
    ],
)
def test_listing_identity_refuses_other_urls(url):
    with pytest.raises(NotAListing):
        canonical_listing_identity(url)


def test_grade_keys():
    assert grade_keys.raw("A") == "raw:A"
    assert grade_keys.is_raw("raw:play") and not grade_keys.is_raw("graded:unknown")
    assert grade_keys.graded("PSA", "10") == "graded:PSA:10"
    assert grade_keys.graded("PSA", None) == grade_keys.GRADED_UNKNOWN
    for key in ("raw:A", "raw:damaged", "graded:PSA:10:flawed", "graded:BGS:9.5"):
        assert grade_keys.is_valid(key)
    assert not grade_keys.is_valid("raw:mint")
