from worker.jobs.ingest_snkrdunk_candidate_prices import ingest_snkrdunk_candidate_prices
from worker.models import Card, PriceObservation, Source, SnkrdunkCandidate


def seed_source_and_card(db_session) -> tuple[Source, Card]:
    source = Source(name="snkrdunk", base_url="https://snkrdunk.com")
    card = Card(
        card_code="OP01-001", name_en="Monkey D. Luffy", name_jp="モンキー・D・ルフィ",
        set_code="OP01", rarity="L", variant=None, language="jp",
    )
    db_session.add(source)
    db_session.add(card)
    db_session.flush()
    return source, card


def make_candidate(db_session, card, **overrides) -> SnkrdunkCandidate:
    fields = dict(
        source_url="https://snkrdunk.com/trading-cards/op01-001-luffy-l",
        title="OP01-001 Monkey D. Luffy L",
        price_jpy=1500,
        listing_count=3,
        condition_label="near_mint",
        detected_card_code="OP01-001",
        match_status="matched",
        matched_card_id=card.id,
        match_confidence=1.0,
    )
    fields.update(overrides)
    candidate = SnkrdunkCandidate(**fields)
    db_session.add(candidate)
    db_session.flush()
    return candidate


def test_matched_candidate_creates_price_observation(db_session):
    _, card = seed_source_and_card(db_session)
    candidate = make_candidate(db_session, card)

    summary = ingest_snkrdunk_candidate_prices(db=db_session)

    assert summary.candidates_checked == 1
    assert summary.observations_created == 1
    assert summary.observations_skipped_duplicate == 0
    assert summary.candidates_skipped_unmatched == 0
    assert summary.candidates_skipped_missing_price == 0

    observation = db_session.query(PriceObservation).one()
    assert observation.card_id == card.id
    assert observation.price_type == "floor"
    assert observation.price_jpy == 1500
    assert observation.condition_label == "near_mint"
    assert observation.listing_count == 3
    assert observation.stock_status is None
    assert observation.raw_snapshot_id is None
    assert observation.candidate_id == candidate.id
    assert observation.observed_at is not None


def test_unmatched_candidate_is_skipped(db_session):
    _, card = seed_source_and_card(db_session)
    make_candidate(
        db_session, card,
        source_url="https://snkrdunk.com/trading-cards/unmatched",
        match_status="unmatched",
        matched_card_id=None,
        match_confidence=None,
    )

    summary = ingest_snkrdunk_candidate_prices(db=db_session)

    assert summary.candidates_checked == 1
    assert summary.candidates_skipped_unmatched == 1
    assert summary.observations_created == 0
    assert db_session.query(PriceObservation).count() == 0


def test_missing_price_is_skipped(db_session):
    _, card = seed_source_and_card(db_session)
    make_candidate(
        db_session, card,
        source_url="https://snkrdunk.com/trading-cards/no-price",
        price_jpy=None,
    )

    summary = ingest_snkrdunk_candidate_prices(db=db_session)

    assert summary.candidates_checked == 1
    assert summary.candidates_skipped_missing_price == 1
    assert summary.observations_created == 0
    assert db_session.query(PriceObservation).count() == 0


def test_duplicate_candidate_does_not_create_duplicate_observation(db_session):
    _, card = seed_source_and_card(db_session)
    make_candidate(db_session, card)

    first = ingest_snkrdunk_candidate_prices(db=db_session)
    assert first.observations_created == 1

    second = ingest_snkrdunk_candidate_prices(db=db_session)
    assert second.candidates_checked == 1
    assert second.observations_created == 0
    assert second.observations_skipped_duplicate == 1
    assert db_session.query(PriceObservation).count() == 1


def test_dry_run_creates_no_observations(db_session):
    _, card = seed_source_and_card(db_session)
    make_candidate(db_session, card)

    summary = ingest_snkrdunk_candidate_prices(db=db_session, dry_run=True)

    assert summary.candidates_checked == 1
    assert summary.observations_created == 1
    assert db_session.query(PriceObservation).count() == 0
