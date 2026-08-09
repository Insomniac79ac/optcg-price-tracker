"""Offline, deterministic tests for snkrdunk_collector.identity. All title
strings are real SNKRDUNK card titles observed live on 2026-08-09, except
where noted as a synthetic malformed case."""

from snkrdunk_collector.identity import parse_card_identity, parse_page_language


def test_leader_parallel_l_dash_p():
    title = "ロロノア・ゾロ L-P [OP01-001] (ブースターパックロマンスドーン)通販・買取・相場｜スニダン"
    assert parse_card_identity(title) == {"card_code": "OP01-001", "rarity": "L", "treatment": "parallel"}


def test_rare_parallel_r_dash_p():
    title = "サンジ R-P [OP01-013] (ブースターパック ロマンスドーン) ¥ 1,500"
    assert parse_card_identity(title) == {"card_code": "OP01-013", "rarity": "R", "treatment": "parallel"}


def test_super_rare_parallel_sr_dash_p():
    title = "ナミ SR-P [OP15-086](ブースターパック「神の島の冒険」) ¥ 21,000"
    assert parse_card_identity(title) == {"card_code": "OP15-086", "rarity": "SR", "treatment": "parallel"}


def test_base_rarity_without_dash_p_is_normal_treatment():
    title = "サンジ R [OP01-013] (プロモーションカードセット2) ¥ 4,500"
    assert parse_card_identity(title) == {"card_code": "OP01-013", "rarity": "R", "treatment": "normal"}


def test_bare_promo_rarity_p_is_not_confused_with_dash_p_suffix():
    title = "モンキー・D・ルフィ P :通常版 [P-159](プロモーションカード「週刊少年ジャンプ2026年33号付録」) ¥ 1,000"
    result = parse_card_identity(title)
    assert result == {"card_code": "P-159", "rarity": "P", "treatment": "normal"}


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
    }


def test_malformed_no_rarity_token_before_bracket_fails_closed():
    assert parse_card_identity("ロロノア・ゾロ [OP01-001]") == {
        "card_code": "OP01-001",
        "rarity": None,
        "treatment": None,
    }


def test_empty_title_fails_closed():
    assert parse_card_identity("") == {"card_code": None, "rarity": None, "treatment": None}


def test_page_language_japanese():
    html = '<html lang="ja" class="inter_62c113fc-module__M00GeW__variable"><body></body></html>'
    assert parse_page_language(html) == "ja"


def test_page_language_english():
    html = '<html lang="en" ><body></body></html>'
    assert parse_page_language(html) == "en"


def test_page_language_missing_is_none():
    assert parse_page_language("<html><body>no lang attr</body></html>") is None
