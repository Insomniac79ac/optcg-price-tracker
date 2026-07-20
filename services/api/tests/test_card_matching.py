import pytest

from app.models import Card, SnkrdunkCandidate
from app.services.card_matching import (
    calculate_candidate_match,
    detect_variant,
    rank_candidate_matches,
)


def make_card(**overrides) -> Card:
    fields = dict(
        id=1,
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        name_jp="モンキー・D・ルフィ",
        set_code="OP01",
        rarity="L",
        variant="base",
        language="jp",
        character="Luffy",
        card_type="Leader",
        color="Red",
        artist=None,
    )
    fields.update(overrides)
    return Card(**{k: v for k, v in fields.items() if k != "id"})


def make_candidate(**overrides) -> SnkrdunkCandidate:
    # Japanese title text by default, matching card.language="jp" - avoids
    # an incidental "language mismatch" penalty (see _detect_language) in
    # tests that aren't specifically exercising that signal.
    fields = dict(
        source_url="https://snkrdunk.com/trading-cards/example",
        title="OP01-001 モンキー・D・ルフィ L",
        normalized_title="OP01-001 モンキー・D・ルフィ L",
        raw_text="Luffy",
        detected_card_code="OP01-001",
        detected_set_code="OP01",
        detected_rarity="L",
        detected_variant=None,
        condition_label=None,
    )
    fields.update(overrides)
    return SnkrdunkCandidate(**fields)


def test_exact_card_code_match_scores_high(db_session):
    card = make_card()
    card.id = 1
    candidate = make_candidate()

    result = calculate_candidate_match(candidate, card)

    assert result.exact_card_code_match is True
    assert result.score >= 90
    assert result.confidence_label == "exact"
    assert "exact card_code match" in result.explanation.positive


def test_set_code_mismatch_caps_score(db_session):
    card = make_card()
    card.id = 1
    candidate = make_candidate(
        title="モンキー・D・ルフィ",
        normalized_title="モンキー・D・ルフィ",
        raw_text="OP01-001 Monkey D. Luffy",
        detected_card_code=None,
        detected_set_code="OP02",
    )

    result = calculate_candidate_match(candidate, card)

    assert "set_code mismatch" in result.explanation.negative
    assert result.score <= 70
    assert "set_code_mismatch_cap_70" in result.explanation.caps_applied


def test_variant_mismatch_caps_score(db_session):
    card = make_card(variant="base")
    card.id = 1
    candidate = make_candidate(
        title="OP01-001 モンキー・D・ルフィ パラレル",
        normalized_title="OP01-001 モンキー・D・ルフィ パラレル",
        raw_text="Luffy Leader Red",
        detected_variant="パラレル",
    )

    result = calculate_candidate_match(candidate, card)

    assert "variant mismatch" in result.explanation.negative
    assert result.score <= 75
    assert "variant_mismatch_cap_75" in result.explanation.caps_applied


def test_name_en_partial_match_works(db_session):
    card = make_card()
    card.id = 1
    candidate = make_candidate(
        detected_card_code=None,
        detected_set_code=None,
        detected_rarity=None,
        title="Monkey D. Luffy playmat bundle",
        normalized_title="Monkey D. Luffy playmat bundle",
    )

    result = calculate_candidate_match(candidate, card)

    assert "partial name_en match" in result.explanation.positive
    assert result.score > 0


def test_name_jp_partial_match_works(db_session):
    card = make_card()
    card.id = 1
    candidate = make_candidate(
        detected_card_code=None,
        detected_set_code=None,
        detected_rarity=None,
        title="モンキー・D・ルフィ グッズセット",
        normalized_title="モンキー・D・ルフィ グッズセット",
    )

    result = calculate_candidate_match(candidate, card)

    assert "partial name_jp match" in result.explanation.positive
    assert result.score > 0


def test_detect_variant_recognizes_japanese_keywords():
    assert detect_variant("OP01-001 パラレル") == "parallel"
    assert detect_variant("OP01-001 マンガ") == "manga"
    assert detect_variant(None) is None
    assert detect_variant("nothing relevant here") is None


def test_ambiguous_tie_detection(db_session):
    card_a = Card(
        card_code="OP01-013", name_en="Roronoa Zoro", name_jp="ロロノア・ゾロ",
        set_code="OP01", rarity="SR", variant="base", language="jp",
    )
    card_b = Card(
        card_code="OP01-024", name_en="Nami", name_jp="ナミ",
        set_code="OP01", rarity="SR", variant="base", language="jp",
    )
    db_session.add_all([card_a, card_b])
    db_session.commit()

    candidate = SnkrdunkCandidate(
        source_url="https://snkrdunk.com/trading-cards/tie-example",
        title="OP01 SR",
        normalized_title="OP01 SR",
        detected_card_code=None,
        detected_set_code="OP01",
        detected_rarity="SR",
    )
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)

    results = rank_candidate_matches(db_session, candidate)

    assert len(results) == 2
    assert results[0].score == results[1].score
    assert results[0].ambiguous is True
    assert results[1].ambiguous is True


def test_unmatched_candidate_remains_unmatched(db_session):
    card = Card(
        card_code="OP01-001", name_en="Monkey D. Luffy", name_jp="モンキー・D・ルフィ",
        set_code="OP01", rarity="L", variant="base", language="jp",
    )
    db_session.add(card)
    db_session.commit()

    candidate = SnkrdunkCandidate(
        source_url="https://snkrdunk.com/trading-cards/totally-unrelated",
        title="謎のリスティング",
        normalized_title="謎のリスティング",
    )
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)

    results = rank_candidate_matches(db_session, candidate)

    assert results == []


def test_exact_card_code_wins_despite_close_runner_up(db_session):
    """An exact card_code match should never be marked ambiguous, even if a
    lower-signal runner-up scores close to it."""
    exact_card = Card(
        card_code="OP01-001", name_en="Monkey D. Luffy", name_jp="モンキー・D・ルフィ",
        set_code="OP01", rarity="L", variant="base", language="jp",
    )
    close_card = Card(
        card_code="OP01-002", name_en="Monkey D Luffy Alt", name_jp="モンキー・D・ルフィ",
        set_code="OP01", rarity="L", variant="base", language="jp",
    )
    db_session.add_all([exact_card, close_card])
    db_session.commit()

    candidate = SnkrdunkCandidate(
        source_url="https://snkrdunk.com/trading-cards/op01-001-luffy",
        title="OP01-001 モンキー・D・ルフィ",
        normalized_title="OP01-001 モンキー・D・ルフィ",
        detected_card_code="OP01-001",
        detected_set_code="OP01",
        detected_rarity="L",
    )
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)

    results = rank_candidate_matches(db_session, candidate)

    assert results[0].card_code == "OP01-001"
    assert results[0].exact_card_code_match is True
    assert results[0].ambiguous is False
