"""Offline, deterministic tests for snkrdunk_collector.identity. All title
strings are real SNKRDUNK card titles observed live on 2026-08-09, except
where noted as a synthetic malformed case."""

from snkrdunk_collector.identity import (
    normalize_card_name,
    normalize_set_token_to_release_product_code,
    parse_card_identity,
    parse_page_language,
    parse_release_text,
    set_token_from_card_code,
)


def test_leader_parallel_l_dash_p():
    title = "ロロノア・ゾロ L-P [OP01-001] (ブースターパックロマンスドーン)通販・買取・相場｜スニダン"
    assert parse_card_identity(title) == {
        "card_code": "OP01-001",
        "rarity": "L",
        "treatment": "parallel",
        "name": "ロロノア・ゾロ",
        "release_text": "ブースターパックロマンスドーン",
    }


def test_rare_parallel_r_dash_p():
    title = "サンジ R-P [OP01-013] (ブースターパック ロマンスドーン) ¥ 1,500"
    assert parse_card_identity(title) == {
        "card_code": "OP01-013",
        "rarity": "R",
        "treatment": "parallel",
        "name": "サンジ",
        "release_text": "ブースターパック ロマンスドーン",
    }


def test_super_rare_parallel_sr_dash_p():
    title = "ナミ SR-P [OP15-086](ブースターパック「神の島の冒険」) ¥ 21,000"
    assert parse_card_identity(title) == {
        "card_code": "OP15-086",
        "rarity": "SR",
        "treatment": "parallel",
        "name": "ナミ",
        "release_text": "ブースターパック「神の島の冒険」",
    }


def test_base_rarity_without_dash_p_is_normal_treatment():
    title = "サンジ R [OP01-013] (プロモーションカードセット2) ¥ 4,500"
    assert parse_card_identity(title) == {
        "card_code": "OP01-013",
        "rarity": "R",
        "treatment": "normal",
        "name": "サンジ",
        "release_text": "プロモーションカードセット2",
    }


def test_bare_promo_rarity_p_is_not_confused_with_dash_p_suffix():
    title = "モンキー・D・ルフィ P :通常版 [P-159](プロモーションカード「週刊少年ジャンプ2026年33号付録」) ¥ 1,000"
    result = parse_card_identity(title)
    assert result["card_code"] == "P-159"
    assert result["rarity"] == "P"
    assert result["treatment"] == "normal"
    # The ":"-prefixed descriptor token is stripped, not absorbed into the name.
    assert result["name"] == "モンキー・D・ルフィ"


def test_unrelated_dash_p_like_suffix_rsp_is_not_treated_as_parallel():
    title = "モンキー・D・ルフィ SEC-RSP (レッドコミパラ) [OP13-118](ブースターパック「受け継がれる意志」) ¥ 3,200,000"
    result = parse_card_identity(title)
    assert result["card_code"] == "OP13-118"
    assert result["rarity"] is None
    assert result["treatment"] is None


def test_malformed_no_card_code_bracket_fails_closed():
    assert parse_card_identity("ロロノア・ゾロ L-P ブースターパックロマンスドーン") == {
        "card_code": None,
        "rarity": None,
        "treatment": None,
        "name": None,
        "release_text": None,
    }


def test_malformed_no_rarity_token_before_bracket_fails_closed():
    result = parse_card_identity("ロロノア・ゾロ [OP01-001]")
    assert result["card_code"] == "OP01-001"
    assert result["rarity"] is None
    assert result["treatment"] is None


def test_empty_title_fails_closed():
    assert parse_card_identity("") == {
        "card_code": None,
        "rarity": None,
        "treatment": None,
        "name": None,
        "release_text": None,
    }


# --- release / set extraction -------------------------------------------------


def test_release_text_read_from_parenthetical_after_card_code():
    title = "ロロノア・ゾロ L-P [OP01-001] (ブースターパックロマンスドーン)通販・買取・相場｜スニダン"
    assert parse_release_text(title) == "ブースターパックロマンスドーン"


def test_release_text_ignores_parenthetical_before_the_card_code():
    """Only the parenthetical AFTER the bracket is the release - a
    descriptor before it (here "(レッドコミパラ)") must never be taken."""
    title = "モンキー・D・ルフィ SEC-RSP (レッドコミパラ) [OP13-118](ブースターパック「受け継がれる意志」)"
    assert parse_release_text(title) == "ブースターパック「受け継がれる意志」"


def test_release_text_absent_is_none():
    assert parse_release_text("ロロノア・ゾロ L-P [OP01-001]通販・買取・相場｜スニダン") is None


def test_set_token_from_card_code():
    assert set_token_from_card_code("OP01-001") == "OP01"
    assert set_token_from_card_code("OP04-118") == "OP04"
    assert set_token_from_card_code("ST29-008") == "ST29"
    assert set_token_from_card_code("P-159") == "P"


def test_set_token_from_malformed_card_code_is_none():
    assert set_token_from_card_code("not-a-code") is None
    assert set_token_from_card_code(None) is None
    assert set_token_from_card_code("") is None


def test_set_token_normalizes_to_release_product_code_convention():
    """card_prints.release_product_code hyphenates letters from digits."""
    assert normalize_set_token_to_release_product_code("OP01") == "OP-01"
    assert normalize_set_token_to_release_product_code("OP04") == "OP-04"
    assert normalize_set_token_to_release_product_code("ST29") == "ST-29"
    assert normalize_set_token_to_release_product_code("PRB02") == "PRB-02"


def test_set_token_without_digits_is_left_unhyphenated():
    assert normalize_set_token_to_release_product_code("P") == "P"


def test_unseen_set_normalizes_without_any_lookup_table():
    """A set this collector has never encountered still normalizes - the
    rule is structural, not a per-set mapping."""
    assert normalize_set_token_to_release_product_code("OP99") == "OP-99"


# --- name normalization -------------------------------------------------------


def test_normalize_card_name_strips_whitespace_only():
    assert normalize_card_name(" ロロノア・ゾロ ") == "ロロノア・ゾロ"
    assert normalize_card_name("モンキー・D・ルフィ") == "モンキー・D・ルフィ"


def test_normalize_card_name_folds_fullwidth_latin_to_halfwidth():
    """NFKC folding only - generic source formatting, never card aliasing."""
    assert normalize_card_name("Ｄ") == normalize_card_name("D")


def test_normalize_card_name_none_and_empty():
    assert normalize_card_name(None) is None
    assert normalize_card_name("   ") is None


# --- page language ------------------------------------------------------------


def test_page_language_japanese():
    html = '<html lang="ja" class="inter_62c113fc-module__M00GeW__variable"><body></body></html>'
    assert parse_page_language(html) == "ja"


def test_page_language_english():
    html = '<html lang="en" ><body></body></html>'
    assert parse_page_language(html) == "en"


def test_page_language_missing_is_none():
    assert parse_page_language("<html><body>no lang attr</body></html>") is None
