from types import SimpleNamespace

from worker.matching import opcg_normalizer as norm
from worker.matching.snkrdunk_matcher import is_graded_condition, match_candidate


def make_card(**kwargs):
    defaults = dict(
        id=1,
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        name_jp="モンキー・D・ルフィ",
        set_code="OP01",
        rarity="L",
        variant=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def make_candidate(**kwargs):
    defaults = dict(
        normalized_title="",
        detected_card_code=None,
        detected_set_code=None,
        detected_rarity=None,
        detected_variant=None,
        condition_label=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# --- opcg_normalizer ---------------------------------------------------


def test_normalize_title_collapses_whitespace_and_width():
    assert norm.normalize_title("  ONE PIECEカードゲーム　OP01-001  ") == "ONE PIECEカードゲーム OP01-001"


def test_normalize_title_handles_none_and_empty():
    assert norm.normalize_title(None) == ""
    assert norm.normalize_title("") == ""


def test_extract_card_code_finds_set_and_number():
    assert norm.extract_card_code("ONE PIECEカードゲーム OP01-001 モンキー・D・ルフィ L") == "OP01-001"
    assert norm.extract_card_code("no code here") is None


def test_extract_set_code_prefers_card_code_prefix():
    assert norm.extract_set_code("whatever", card_code="OP02-025") == "OP02"


def test_extract_set_code_falls_back_to_bracket():
    assert norm.extract_set_code("[OP02] ニコ・ロビン R") == "OP02"


def test_extract_rarity_finds_known_token():
    assert norm.extract_rarity("OP01-001 モンキー・D・ルフィ L") == "L"
    assert norm.extract_rarity("[OP04] シャンクス SEC") == "SEC"
    assert norm.extract_rarity("no rarity token") is None


def test_extract_variant_detects_keyword():
    assert norm.extract_variant("OP05-119 カイドウ パラレル") == "parallel"
    assert norm.extract_variant("OP01-001 モンキー・D・ルフィ L") is None


# --- snkrdunk_matcher ----------------------------------------------------


def test_is_graded_condition_detects_grading_companies():
    assert is_graded_condition("PSA10")
    assert is_graded_condition("BGS 9.5")
    assert is_graded_condition("ARS")
    assert not is_graded_condition("中古")
    assert not is_graded_condition(None)


def test_tier1_exact_card_code_auto_matches():
    cards = [make_card(id=1, card_code="OP01-001")]
    candidate = make_candidate(
        normalized_title="ONE PIECEカードゲーム OP01-001 モンキー・D・ルフィ L",
        detected_card_code="OP01-001",
    )

    result = match_candidate(candidate, cards)

    assert result.match_status == "matched"
    assert result.matched_card_id == 1
    assert result.match_confidence >= 0.92


def test_tier1_ambiguous_card_code_is_ambiguous():
    cards = [
        make_card(id=1, card_code="OP01-001", variant=None),
        make_card(id=2, card_code="OP01-001", variant="parallel"),
    ]
    candidate = make_candidate(detected_card_code="OP01-001", normalized_title="OP01-001")

    result = match_candidate(candidate, cards)

    assert result.match_status == "ambiguous"
    assert result.matched_card_id is None


def test_tier2_name_and_set_code_auto_matches_without_card_code():
    cards = [
        make_card(id=1, card_code="OP01-001", set_code="OP01", name_jp="モンキー・D・ルフィ"),
        make_card(id=2, card_code="OP02-025", set_code="OP02", name_jp="ニコ・ロビン"),
    ]
    candidate = make_candidate(
        normalized_title="[OP02] ニコ・ロビン R",
        detected_card_code=None,
        detected_set_code="OP02",
    )

    result = match_candidate(candidate, cards)

    assert result.match_status == "matched"
    assert result.matched_card_id == 2
    assert result.match_confidence == 0.93


def test_tier3_name_rarity_variant_is_advisory_only():
    # No set_code detected, so tier 2 is skipped; two reprints share a name,
    # disambiguated only by rarity + variant, which is never auto-match eligible.
    cards = [
        make_card(id=1, card_code="OP05-119", set_code="OP05", name_jp="カイドウ", rarity="SEC", variant=None),
        make_card(id=2, card_code="OP05-119P", set_code="OP05", name_jp="カイドウ", rarity="SEC", variant="parallel"),
    ]
    candidate = make_candidate(
        normalized_title="カイドウ SEC パラレル",
        detected_card_code=None,
        detected_set_code=None,
        detected_rarity="SEC",
        detected_variant="parallel",
    )

    result = match_candidate(candidate, cards)

    assert result.match_status == "suggested"
    assert result.matched_card_id == 2


def test_tier4_fuzzy_match_is_always_advisory():
    cards = [make_card(id=1, name_jp="モンキー・D・ルフィ", name_en="Monkey D. Luffy")]
    candidate = make_candidate(normalized_title="Monkey D Luffy misprint listing")

    result = match_candidate(candidate, cards)

    assert result.match_status == "suggested"
    assert result.matched_card_id == 1


def test_no_match_found_returns_unmatched_with_no_card():
    cards = [make_card(id=1, name_jp="モンキー・D・ルフィ", name_en="Monkey D. Luffy")]
    candidate = make_candidate(normalized_title="completely unrelated listing text")

    result = match_candidate(candidate, cards)

    assert result.match_status == "unmatched"
    assert result.matched_card_id is None


def test_graded_condition_forces_suggested_even_on_exact_code_match():
    cards = [make_card(id=1, card_code="OP01-001")]
    candidate = make_candidate(
        normalized_title="OP01-001 モンキー・D・ルフィ L",
        detected_card_code="OP01-001",
        condition_label="PSA10",
    )

    result = match_candidate(candidate, cards)

    assert result.match_status == "suggested"
    assert result.matched_card_id == 1


def test_auto_match_threshold_can_reject_tier2_confidence():
    cards = [make_card(id=1, card_code="OP01-001", set_code="OP01", name_jp="モンキー・D・ルフィ")]
    candidate = make_candidate(
        normalized_title="モンキー・D・ルフィ",
        detected_card_code=None,
        detected_set_code="OP01",
    )

    result = match_candidate(candidate, cards, auto_match_threshold=0.95)

    assert result.match_status == "suggested"
    assert result.matched_card_id == 1
