"""PostgreSQL semantics for the persisted proposal-review aggregations.

Uses only TEST_POSTGRES_URL (the repository's disposable test database).  It
never points at staging or production and skips when no local test server is
available.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db import Base
from app.services.source_mapping_proposal_review import (
    ReviewFilters,
    get_persisted_release_summary,
    get_persisted_review_summary,
    list_review_groups,
)
from tests.test_source_mapping_proposal_review import (
    _canonical,
    _print,
    _proposal,
    _release,
    _snkr,
    _source,
    _yuyu,
)

TEST_POSTGRES_URL = os.environ.get(
    "TEST_POSTGRES_URL",
    "postgresql+psycopg://opcg:opcg@localhost:5544/opcg_test",
)


@pytest.fixture()
def postgres_session():
    engine = create_engine(TEST_POSTGRES_URL)
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.skip(f"No PostgreSQL server reachable at {TEST_POSTGRES_URL}")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_review_aggregations_and_enriched_list_run_on_postgresql(postgres_session):
    db = postgres_session
    yuyu = _source(db, "yuyutei")
    snkr = _source(db, "snkrdunk")
    release = _release(db, "OP-17")
    canonical = _canonical(db, "OP01-001")
    base = _print(db, canonical, release)
    parallel = _print(db, canonical, release, "p1")
    exact = _proposal(
        db,
        yuyu,
        _yuyu(db, 501, canonical.card_code),
        canonical=canonical,
        release=release,
        status="exact",
        prints=[base],
        recommended=[base],
    )
    _proposal(
        db,
        snkr,
        _snkr(db, 502, canonical.card_code),
        canonical=canonical,
        release=release,
        status="ambiguous",
        prints=[base, parallel],
    )
    _proposal(
        db,
        snkr,
        _snkr(db, 503, canonical.card_code, release_code="UNKNOWN"),
        canonical=canonical,
        status="release_unresolved",
    )
    db.commit()

    summary = get_persisted_review_summary(db)
    assert summary["total_current_groups"] == 3
    assert summary["total_current_alternatives"] == 3
    assert summary["by_source_and_resolution"]["yuyutei"]["exact"] == 1
    assert summary["by_source_and_resolution"]["snkrdunk"]["ambiguous"] == 1

    releases = get_persisted_release_summary(db)
    by_id = {row["release_product_id"]: row for row in releases["items"]}
    assert by_id[release.id]["total_active_verified_japanese_card_prints"] == 2
    assert by_id[release.id]["alternatives"] == 3
    assert by_id[None]["release_unresolved_pending_groups"] == 1

    listing = list_review_groups(
        db,
        ReviewFilters(
            proposal_group_id=exact.id,
            has_candidate_image=True,
            has_recommended_alternative=True,
            limit=25,
        ),
    )
    assert listing["pagination"].total == 1
    assert (
        listing["items"][0]["recommended_print"]["release"]["official_code"] == "OP-17"
    )
