"""Ingestion is driven by the listing's APPROVED MAPPING, not by the
candidate's legacy card pointer - see the job's module docstring.

Every test that expects an observation therefore seeds a mapping for the
candidate's source_url, because that is what production requires. The
`legacy_mapping` helper keeps the pre-4F shape (card_id set, no print) so the
old behaviour stays proven; `print_mapping` is the new print-authoritative
shape (card_print_id set, card_id NULL).
"""

from worker.jobs.ingest_snkrdunk_candidate_prices import ingest_snkrdunk_candidate_prices
from worker.models import Card, PriceObservation, Source, SnkrdunkCandidate, SourceCardMapping

CANDIDATE_URL = "https://snkrdunk.com/trading-cards/op01-001-luffy-l"


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


def legacy_mapping(db_session, source, card, **overrides) -> SourceCardMapping:
    """A mapping as it looked before exact prints: a legacy card, no print."""
    fields = dict(
        card_id=card.id,
        source_id=source.id,
        source_card_id="OP01-001",
        source_url=CANDIDATE_URL,
        is_active=True,
        review_status="approved",
    )
    fields.update(overrides)
    mapping = SourceCardMapping(**fields)
    db_session.add(mapping)
    db_session.flush()
    return mapping


def print_mapping(db_session, source, card_print_id: int = 4242, **overrides) -> SourceCardMapping:
    """A print-authoritative mapping: the exact print, and no legacy card.

    card_print_id is a plain integer in worker's mirror (the api's migrations
    own the card_prints FK), so this needs no card_prints row - the
    cross-table lineage constraints are proven against the real schema in
    tests/test_refresh_prices_print_lineage_postgres.py and the api's
    end-to-end test, not here.
    """
    fields = dict(
        card_id=None,
        source_id=source.id,
        card_print_id=card_print_id,
        source_card_id="OP01-001",
        source_url=CANDIDATE_URL,
        is_active=True,
        review_status="approved",
    )
    fields.update(overrides)
    mapping = SourceCardMapping(**fields)
    db_session.add(mapping)
    db_session.flush()
    return mapping


def make_candidate(db_session, card, **overrides) -> SnkrdunkCandidate:
    fields = dict(
        source_url=CANDIDATE_URL,
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


def test_legacy_mapping_candidate_creates_card_keyed_observation(db_session):
    """The pre-4F shape, unchanged: a legacy mapping still prices, still
    stamps card_id, and still stamps neither lineage column."""
    source, card = seed_source_and_card(db_session)
    legacy_mapping(db_session, source, card)
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
    assert observation.source_card_mapping_id is None
    assert observation.card_print_id is None


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
    source, card = seed_source_and_card(db_session)
    legacy_mapping(db_session, source, card, source_url="https://snkrdunk.com/trading-cards/no-price")
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
    source, card = seed_source_and_card(db_session)
    legacy_mapping(db_session, source, card)
    make_candidate(db_session, card)

    first = ingest_snkrdunk_candidate_prices(db=db_session)
    assert first.observations_created == 1

    second = ingest_snkrdunk_candidate_prices(db=db_session)
    assert second.candidates_checked == 1
    assert second.observations_created == 0
    assert second.observations_skipped_duplicate == 1
    assert db_session.query(PriceObservation).count() == 1


def test_dry_run_creates_no_observations(db_session):
    source, card = seed_source_and_card(db_session)
    legacy_mapping(db_session, source, card)
    make_candidate(db_session, card)

    summary = ingest_snkrdunk_candidate_prices(db=db_session, dry_run=True)

    assert summary.candidates_checked == 1
    assert summary.observations_created == 1
    assert db_session.query(PriceObservation).count() == 0


# --- the print-authoritative path ------------------------------------------


def test_print_mapping_creates_observation_with_null_card_id_and_print_lineage(db_session):
    """The capability this tranche exists to deliver: a listing approved onto
    an exact print, with no legacy card anywhere in the chain, still prices."""
    source, card = seed_source_and_card(db_session)
    mapping = print_mapping(db_session, source)
    candidate = make_candidate(db_session, card, matched_card_id=None, match_confidence=None)

    summary = ingest_snkrdunk_candidate_prices(db=db_session)

    assert summary.observations_created == 1
    assert summary.candidates_skipped_unmatched == 0
    assert summary.candidates_skipped_no_approved_mapping == 0

    observation = db_session.query(PriceObservation).one()
    assert observation.card_id is None
    assert observation.card_print_id == mapping.card_print_id
    assert observation.source_card_mapping_id == mapping.id
    assert observation.source_id == source.id
    assert observation.price_jpy == 1500
    assert observation.candidate_id == candidate.id


def test_mapping_lineage_wins_over_the_candidates_legacy_card_pointer(db_session):
    """Ingestion is no longer keyed from candidate.matched_card_id. A
    candidate still carrying a stale legacy pointer must not drag it onto the
    observation - the approved mapping decides, and this one names no card."""
    source, card = seed_source_and_card(db_session)
    mapping = print_mapping(db_session, source)
    make_candidate(db_session, card, matched_card_id=card.id)

    ingest_snkrdunk_candidate_prices(db=db_session)

    observation = db_session.query(PriceObservation).one()
    assert observation.card_id is None
    assert observation.card_print_id == mapping.card_print_id


def test_repeated_ingestion_of_a_print_mapping_is_idempotent(db_session):
    source, card = seed_source_and_card(db_session)
    print_mapping(db_session, source)
    make_candidate(db_session, card, matched_card_id=None)

    first = ingest_snkrdunk_candidate_prices(db=db_session)
    second = ingest_snkrdunk_candidate_prices(db=db_session)
    third = ingest_snkrdunk_candidate_prices(db=db_session)

    assert first.observations_created == 1
    assert second.observations_created == 0
    assert second.observations_skipped_duplicate == 1
    assert third.observations_skipped_duplicate == 1
    assert db_session.query(PriceObservation).count() == 1


def test_two_prints_of_one_card_do_not_deduplicate_against_each_other(db_session):
    """The dedup fallback must key on the lineage pair, not on card_id. Both
    rows have card_id NULL and identical price/condition on the same day; only
    the print distinguishes them, and suppressing the second would be the
    card-code merge this whole series removes."""
    source, card = seed_source_and_card(db_session)
    base = print_mapping(db_session, source, card_print_id=4242)
    parallel = print_mapping(
        db_session, source, card_print_id=4243,
        source_url="https://snkrdunk.com/trading-cards/op01-001-luffy-l-parallel",
    )
    make_candidate(db_session, card, matched_card_id=None)
    make_candidate(
        db_session, card,
        source_url="https://snkrdunk.com/trading-cards/op01-001-luffy-l-parallel",
        matched_card_id=None,
    )

    summary = ingest_snkrdunk_candidate_prices(db=db_session)

    assert summary.observations_created == 2
    print_ids = {o.card_print_id for o in db_session.query(PriceObservation).all()}
    assert print_ids == {base.card_print_id, parallel.card_print_id}


# --- the mapping gate is fail-closed ---------------------------------------


def test_candidate_with_no_mapping_is_skipped(db_session):
    _, card = seed_source_and_card(db_session)
    make_candidate(db_session, card)

    summary = ingest_snkrdunk_candidate_prices(db=db_session)

    assert summary.observations_created == 0
    assert summary.candidates_skipped_no_approved_mapping == 1
    assert db_session.query(PriceObservation).count() == 0


def test_needs_review_mapping_does_not_price(db_session):
    source, card = seed_source_and_card(db_session)
    print_mapping(db_session, source, review_status="needs_review")
    make_candidate(db_session, card, matched_card_id=None)

    summary = ingest_snkrdunk_candidate_prices(db=db_session)

    assert summary.candidates_skipped_no_approved_mapping == 1
    assert db_session.query(PriceObservation).count() == 0


def test_inactive_mapping_does_not_price(db_session):
    source, card = seed_source_and_card(db_session)
    print_mapping(db_session, source, is_active=False)
    make_candidate(db_session, card, matched_card_id=None)

    summary = ingest_snkrdunk_candidate_prices(db=db_session)

    assert summary.candidates_skipped_no_approved_mapping == 1
    assert db_session.query(PriceObservation).count() == 0


def test_mapping_naming_neither_print_nor_card_does_not_price(db_session):
    """A mapping with no card_print_id and no card_id identifies nothing, so
    an observation from it would assert nothing. Fail closed."""
    source, card = seed_source_and_card(db_session)
    print_mapping(db_session, source, card_print_id=None)
    make_candidate(db_session, card, matched_card_id=None)

    summary = ingest_snkrdunk_candidate_prices(db=db_session)

    assert summary.candidates_skipped_no_approved_mapping == 1
    assert db_session.query(PriceObservation).count() == 0


def test_suggested_candidate_is_not_priced_by_relaxing_only_matched(db_session):
    """--no-only-matched widens the candidate pre-filter, never the approval
    gate: a suggested listing with no approved mapping still prices nothing."""
    _, card = seed_source_and_card(db_session)
    make_candidate(db_session, card, match_status="suggested")

    summary = ingest_snkrdunk_candidate_prices(db=db_session, only_matched=False)

    assert summary.candidates_skipped_unmatched == 0
    assert summary.candidates_skipped_no_approved_mapping == 1
    assert db_session.query(PriceObservation).count() == 0
