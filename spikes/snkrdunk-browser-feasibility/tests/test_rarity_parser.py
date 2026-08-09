"""Offline, deterministic tests for spike.parse_card_identity - the generic
"<rarity>-P" => parallel treatment parser. All title strings here are real
SNKRDUNK card titles observed live on 2026-08-09 (search results for
OP01-001/OP01-002/OP01-013 and the ONE PIECE category page), not
hand-invented fixtures, except where noted as a synthetic malformed case."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spike import parse_card_identity  # noqa: E402


def test_leader_parallel_l_dash_p():
    title = "ロロノア・ゾロ L-P [OP01-001] (ブースターパックロマンスドーン)通販・買取・相場｜スニダン"
    result = parse_card_identity(title)
    assert result == {"card_code": "OP01-001", "rarity": "L", "treatment": "parallel"}


def test_rare_parallel_r_dash_p():
    title = "サンジ R-P [OP01-013] (ブースターパック ロマンスドーン) ¥ 1,500"
    result = parse_card_identity(title)
    assert result == {"card_code": "OP01-013", "rarity": "R", "treatment": "parallel"}


def test_super_rare_parallel_sr_dash_p():
    title = "ナミ SR-P [OP15-086](ブースターパック「神の島の冒険」) ¥ 21,000"
    result = parse_card_identity(title)
    assert result == {"card_code": "OP15-086", "rarity": "SR", "treatment": "parallel"}


def test_secret_parallel_sec_dash_p():
    title = "モンキー・D・ルフィ SEC-P [OP05-119] (ブースターパック 新時代の主役) ¥ 15,999"
    result = parse_card_identity(title)
    assert result == {"card_code": "OP05-119", "rarity": "SEC", "treatment": "parallel"}


def test_base_rarity_without_dash_p_is_normal_treatment():
    title = "サンジ R [OP01-013] (プロモーションカードセット2) ¥ 4,500"
    result = parse_card_identity(title)
    assert result == {"card_code": "OP01-013", "rarity": "R", "treatment": "normal"}


def test_leader_base_rarity_without_dash_p():
    title = "トラファルガー・ロー L [OP01-002] (ブースターパック ロマンスドーン) 出品待ち"
    result = parse_card_identity(title)
    assert result == {"card_code": "OP01-002", "rarity": "L", "treatment": "normal"}


def test_bare_promo_rarity_p_is_not_confused_with_dash_p_suffix():
    # Rarity "P" (Promo) has no dash - must not be conflated with the
    # "<rarity>-P" parallel suffix pattern.
    title = "モンキー・D・ルフィ P :通常版 [P-159](プロモーションカード「週刊少年ジャンプ2026年33号付録」) ¥ 1,000"
    result = parse_card_identity(title)
    assert result["card_code"] == "P-159"
    assert result["rarity"] == "P"
    assert result["treatment"] == "normal"


def test_colon_suffixed_descriptor_between_rarity_and_bracket_is_skipped():
    title = "モンキー・D・ルフィ L :開封済 [OP13-001](プロモーションカード「一番くじ ワンピースカードゲーム 購入特典」) ¥ 2,500"
    result = parse_card_identity(title)
    assert result == {"card_code": "OP13-001", "rarity": "L", "treatment": "normal"}


def test_unrelated_dash_p_like_suffix_rsp_is_not_treated_as_parallel():
    # "-RSP" (a distinct "red comic parallel" marker seen live on OP13-118)
    # superficially ends in "P" but is not the "<rarity>-P" pattern - must
    # fail closed (rarity/treatment unknown), never be mis-read as "parallel".
    title = "モンキー・D・ルフィ SEC-RSP (レッドコミパラ) [OP13-118](ブースターパック「受け継がれる意志」) ¥ 3,200,000"
    result = parse_card_identity(title)
    assert result["card_code"] == "OP13-118"
    assert result["rarity"] is None
    assert result["treatment"] is None


def test_unrelated_dash_p_text_after_bracket_is_never_scanned():
    # A "-P"-like substring appearing only after the [card_code] bracket
    # (e.g. in a set/box descriptor) must never be picked up - the parser
    # only looks at the token immediately preceding the bracket.
    title = "ロロノア・ゾロ L-P [OP01-001] (SNK-P スペシャルドロップ商品)"
    result = parse_card_identity(title)
    assert result == {"card_code": "OP01-001", "rarity": "L", "treatment": "parallel"}


def test_malformed_no_card_code_bracket_fails_closed():
    title = "ロロノア・ゾロ L-P ブースターパックロマンスドーン"
    result = parse_card_identity(title)
    assert result == {"card_code": None, "rarity": None, "treatment": None}


def test_malformed_no_rarity_token_before_bracket_fails_closed():
    title = "ロロノア・ゾロ [OP01-001]"
    result = parse_card_identity(title)
    assert result == {"card_code": "OP01-001", "rarity": None, "treatment": None}


def test_malformed_garbage_dash_token_fails_closed():
    title = "ロロノア・ゾロ -P- [OP01-001]"
    result = parse_card_identity(title)
    assert result == {"card_code": "OP01-001", "rarity": None, "treatment": None}


def test_empty_title_fails_closed():
    result = parse_card_identity("")
    assert result == {"card_code": None, "rarity": None, "treatment": None}
