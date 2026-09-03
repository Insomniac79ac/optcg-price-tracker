"""The read-only admin view over source_collection_attempts.

WHAT THIS PROTECTS. The attempts table exists because collector failures left
no evidence - mapping 391's cause on 2026-09-02 is permanently unknowable. This
endpoint is how that evidence gets read, so the properties worth pinning are
the ones that would make it misleading rather than merely broken: context that
is resolved but never invented, a summary computed over the whole filtered set
rather than the returned page, and a surface that cannot write.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    CanonicalCard,
    CardPrint,
    PriceObservation,
    Source,
    SourceCardMapping,
    SourceCollectionAttempt,
)

RUN = "batch0001"
OTHER_RUN = "batch0002"
BASE = datetime(2026, 9, 3, 18, 21, 0, tzinfo=timezone.utc)


@pytest.fixture()
def subject(db_session):
    """One source, one print, three mappings - the minimum a batch needs."""
    source = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
    canonical = CanonicalCard(card_code="OP13-050", name_en="Boa", card_type="CHARACTER")
    db_session.add_all([source, canonical])
    db_session.flush()
    card_print = CardPrint(canonical_card_id=canonical.id, language="jp", is_active=True)
    db_session.add(card_print)
    db_session.flush()
    mappings = [
        SourceCardMapping(
            source_id=source.id,
            source_card_id=f"OP13-{i:03d}",
            source_url=f"https://yuyu-tei.jp/sell/opc/card/op13/{10000 + i}",
            card_print_id=card_print.id,
            is_active=True,
            review_status="approved",
        )
        for i in (50, 51, 52)
    ]
    db_session.add_all(mappings)
    db_session.commit()
    return {
        "source_id": source.id,
        "print_id": card_print.id,
        "mapping_ids": [m.id for m in mappings],
        "card_code": "OP13-050",
    }


def _attempt(db_session, subject, ordinal, mapping_id, **overrides):
    values = dict(
        batch_run_id=RUN,
        source_id=subject["source_id"],
        source_card_mapping_id=mapping_id,
        selection_ordinal=ordinal,
        selected_at=BASE,
        started_at=None,
        finished_at=None,
        status="selected",
        failure_stage=None,
        failure_reason=None,
        source_denied=False,
        price_observation_id=None,
    )
    values.update(overrides)
    row = SourceCollectionAttempt(**values)
    db_session.add(row)
    db_session.commit()
    return row


def _written(db_session, subject, ordinal, mapping_id, seconds=6.5, observation_id=None):
    return _attempt(
        db_session, subject, ordinal, mapping_id,
        status="written",
        started_at=BASE + timedelta(seconds=ordinal),
        finished_at=BASE + timedelta(seconds=ordinal + seconds),
        price_observation_id=observation_id,
    )


# --- auth ------------------------------------------------------------------


def test_requires_an_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain = TestClient(app)
    assert plain.get("/admin/collection-attempts").status_code == 401


def test_a_wrong_admin_token_is_rejected(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    bad = TestClient(app, headers={"X-Admin-Token": "nope"})
    assert bad.get("/admin/collection-attempts").status_code == 401


# --- empty state -----------------------------------------------------------


def test_empty_returns_an_empty_summary_not_an_error(client, db_session):
    """Staging has zero rows until the first scheduled run; that must read as
    'nothing recorded yet', not as a failure."""
    response = client.get("/admin/collection-attempts")

    assert response.status_code == 200
    data = response.json()
    assert data["attempts"] == []
    assert data["summary"]["total_attempts"] == 0
    assert data["summary"]["written"] == 0
    assert data["summary"]["by_status"] == {}
    assert data["summary"]["earliest_selected_at"] is None
    assert data["summary"]["latest_finished_at"] is None
    assert data["pagination"]["total"] == 0


# --- ordering and pagination ----------------------------------------------


def test_newest_first_with_a_deterministic_tiebreak(client, db_session, subject):
    """A whole batch shares one selected_at, so id is what actually orders the
    page - without it, page boundaries would be up to the planner."""
    for ordinal, mapping_id in enumerate(subject["mapping_ids"], start=1):
        _written(db_session, subject, ordinal, mapping_id)

    data = client.get("/admin/collection-attempts").json()
    ids = [a["id"] for a in data["attempts"]]
    assert ids == sorted(ids, reverse=True)


def test_a_newer_batch_sorts_above_an_older_one(client, db_session, subject):
    _written(db_session, subject, 1, subject["mapping_ids"][0])
    _attempt(
        db_session, subject, 1, subject["mapping_ids"][1],
        batch_run_id=OTHER_RUN, selected_at=BASE + timedelta(days=1),
        status="written", started_at=BASE + timedelta(days=1),
        finished_at=BASE + timedelta(days=1, seconds=5),
    )

    data = client.get("/admin/collection-attempts").json()
    assert data["attempts"][0]["batch_run_id"] == OTHER_RUN


def test_pagination_pages_without_overlap(client, db_session, subject):
    for ordinal, mapping_id in enumerate(subject["mapping_ids"], start=1):
        _written(db_session, subject, ordinal, mapping_id)

    first = client.get("/admin/collection-attempts", params={"limit": 2}).json()
    second = client.get(
        "/admin/collection-attempts", params={"limit": 2, "offset": 2}
    ).json()

    assert len(first["attempts"]) == 2
    assert len(second["attempts"]) == 1
    assert first["pagination"]["total"] == 3
    assert first["pagination"]["has_next"] is True
    assert second["pagination"]["has_next"] is False
    assert {a["id"] for a in first["attempts"]}.isdisjoint(
        {a["id"] for a in second["attempts"]}
    )


def test_the_limit_is_bounded(client, db_session):
    assert client.get("/admin/collection-attempts", params={"limit": 501}).status_code == 422
    assert client.get("/admin/collection-attempts", params={"limit": 0}).status_code == 422
    assert client.get("/admin/collection-attempts", params={"offset": -1}).status_code == 422


# --- filters ---------------------------------------------------------------


def test_filters_by_batch_run_id(client, db_session, subject):
    _written(db_session, subject, 1, subject["mapping_ids"][0])
    _attempt(
        db_session, subject, 1, subject["mapping_ids"][1],
        batch_run_id=OTHER_RUN, status="skipped", finished_at=BASE,
    )

    data = client.get("/admin/collection-attempts", params={"batch_run_id": OTHER_RUN}).json()
    assert data["summary"]["total_attempts"] == 1
    assert data["attempts"][0]["batch_run_id"] == OTHER_RUN


def test_filters_by_status(client, db_session, subject):
    _written(db_session, subject, 1, subject["mapping_ids"][0])
    _attempt(
        db_session, subject, 2, subject["mapping_ids"][1],
        status="validation_failed", failure_stage="validation",
        failure_reason="price_matches_card_code_or_id_digits:50",
        started_at=BASE, finished_at=BASE + timedelta(seconds=3),
    )

    data = client.get(
        "/admin/collection-attempts", params={"status": "validation_failed"}
    ).json()
    assert data["summary"]["total_attempts"] == 1
    assert data["attempts"][0]["failure_reason"] == "price_matches_card_code_or_id_digits:50"


def test_filters_by_failure_stage(client, db_session, subject):
    _attempt(
        db_session, subject, 1, subject["mapping_ids"][0],
        status="no_extraction_attempted", failure_stage="homepage",
        failure_reason="no_extraction_attempted:classification=None",
        started_at=BASE, finished_at=BASE + timedelta(seconds=30),
    )
    _attempt(
        db_session, subject, 2, subject["mapping_ids"][1],
        status="validation_failed", failure_stage="validation",
        started_at=BASE, finished_at=BASE + timedelta(seconds=3),
    )

    data = client.get(
        "/admin/collection-attempts", params={"failure_stage": "homepage"}
    ).json()
    assert data["summary"]["total_attempts"] == 1
    assert data["attempts"][0]["failure_stage"] == "homepage"


def test_filters_by_source_denied(client, db_session, subject):
    _written(db_session, subject, 1, subject["mapping_ids"][0])
    _attempt(
        db_session, subject, 2, subject["mapping_ids"][1],
        status="skipped", finished_at=BASE, source_denied=True,
        failure_reason="source_denied:static_403",
    )

    denied = client.get(
        "/admin/collection-attempts", params={"source_denied": "true"}
    ).json()
    assert denied["summary"]["total_attempts"] == 1
    assert denied["attempts"][0]["source_denied"] is True

    not_denied = client.get(
        "/admin/collection-attempts", params={"source_denied": "false"}
    ).json()
    assert not_denied["summary"]["total_attempts"] == 1
    assert not_denied["attempts"][0]["source_denied"] is False


def test_filters_by_mapping_and_source(client, db_session, subject):
    target = subject["mapping_ids"][1]
    for ordinal, mapping_id in enumerate(subject["mapping_ids"], start=1):
        _written(db_session, subject, ordinal, mapping_id)

    by_mapping = client.get(
        "/admin/collection-attempts", params={"source_card_mapping_id": target}
    ).json()
    assert by_mapping["summary"]["total_attempts"] == 1
    assert by_mapping["attempts"][0]["source_card_mapping_id"] == target

    by_source = client.get(
        "/admin/collection-attempts", params={"source_id": subject["source_id"]}
    ).json()
    assert by_source["summary"]["total_attempts"] == 3


def test_an_unknown_status_is_a_client_error_not_an_empty_list(client, db_session):
    """A silent [] would read as 'no such attempts' when the truth is 'that
    status cannot exist'."""
    response = client.get("/admin/collection-attempts", params={"status": "nearly_written"})
    assert response.status_code == 400
    assert "Invalid status" in response.json()["detail"]


def test_an_unknown_failure_stage_is_a_client_error(client, db_session):
    response = client.get("/admin/collection-attempts", params={"failure_stage": "vibes"})
    assert response.status_code == 400
    assert "Invalid failure_stage" in response.json()["detail"]


# --- resolved context ------------------------------------------------------


def test_context_is_resolved_for_a_live_mapping(client, db_session, subject):
    _written(db_session, subject, 1, subject["mapping_ids"][0])

    row = client.get("/admin/collection-attempts").json()["attempts"][0]
    assert row["mapping_resolved"] is True
    assert row["source_name"] == "yuyutei"
    assert row["card_print_id"] == subject["print_id"]
    assert row["card_code"] == subject["card_code"]


def test_an_unresolvable_mapping_keeps_its_ids_and_invents_nothing(
    client, db_session, subject
):
    """source_card_mapping_id has no FK precisely so history outlives its
    subject. When the mapping is gone the row must still be returned, with the
    stored ids intact and no fabricated card identity."""
    ghost_mapping_id = 999_999
    _attempt(
        db_session, subject, 1, ghost_mapping_id,
        status="written", started_at=BASE, finished_at=BASE + timedelta(seconds=4),
    )

    row = client.get("/admin/collection-attempts").json()["attempts"][0]
    assert row["source_card_mapping_id"] == ghost_mapping_id  # authoritative
    assert row["mapping_resolved"] is False
    assert row["card_print_id"] is None
    assert row["card_code"] is None
    assert row["status"] == "written"


# --- derived duration ------------------------------------------------------


def test_duration_is_derived_from_the_two_timestamps(client, db_session, subject):
    _written(db_session, subject, 1, subject["mapping_ids"][0], seconds=6.5)

    row = client.get("/admin/collection-attempts").json()["attempts"][0]
    # started_at and finished_at share the same ordinal offset, so the
    # duration is exactly the gap between them.
    assert row["duration_seconds"] == pytest.approx(6.5)


def test_a_skipped_attempt_has_no_start_and_no_duration(client, db_session, subject):
    """The lifecycle case: selected, never started, then terminal."""
    _attempt(
        db_session, subject, 1, subject["mapping_ids"][0],
        status="skipped", started_at=None, finished_at=BASE + timedelta(seconds=90),
        source_denied=True, failure_reason="source_denied:static_403",
    )

    row = client.get("/admin/collection-attempts").json()["attempts"][0]
    assert row["started_at"] is None
    assert row["finished_at"] is not None
    assert row["duration_seconds"] is None


def test_an_in_flight_attempt_has_no_duration_yet(client, db_session, subject):
    _attempt(
        db_session, subject, 1, subject["mapping_ids"][0],
        status="selected", started_at=BASE, finished_at=None,
    )

    row = client.get("/admin/collection-attempts").json()["attempts"][0]
    assert row["duration_seconds"] is None


# --- batch summary ---------------------------------------------------------


def test_the_summary_describes_the_whole_filtered_set_not_the_page(
    client, db_session, subject
):
    _written(db_session, subject, 1, subject["mapping_ids"][0])
    _attempt(
        db_session, subject, 2, subject["mapping_ids"][1],
        status="no_extraction_attempted", failure_stage="homepage",
        started_at=BASE, finished_at=BASE + timedelta(seconds=30),
        source_denied=True,
    )
    _attempt(
        db_session, subject, 3, subject["mapping_ids"][2],
        status="skipped", finished_at=BASE + timedelta(seconds=31),
        source_denied=True, failure_reason="source_denied:static_403",
    )

    data = client.get("/admin/collection-attempts", params={"limit": 1}).json()

    assert len(data["attempts"]) == 1          # one row on the page
    summary = data["summary"]
    assert summary["total_attempts"] == 3      # summary covers all three
    assert summary["started"] == 2             # the skipped one never started
    assert summary["written"] == 1
    assert summary["skipped"] == 1
    assert summary["source_denied"] == 2
    assert summary["still_selected"] == 0
    assert summary["by_status"] == {
        "written": 1,
        "no_extraction_attempted": 1,
        "skipped": 1,
    }
    assert summary["by_failure_stage"] == {"homepage": 1}
    assert summary["earliest_selected_at"] is not None
    assert summary["latest_finished_at"] is not None


def test_a_batch_filtered_summary_answers_that_run_only(client, db_session, subject):
    _written(db_session, subject, 1, subject["mapping_ids"][0])
    _attempt(
        db_session, subject, 1, subject["mapping_ids"][1],
        batch_run_id=OTHER_RUN, status="skipped", finished_at=BASE,
    )

    data = client.get(
        "/admin/collection-attempts", params={"batch_run_id": RUN}
    ).json()
    assert data["summary"]["total_attempts"] == 1
    assert data["summary"]["written"] == 1
    assert data["summary"]["skipped"] == 0


def test_still_selected_counts_the_non_terminal_rows(client, db_session, subject):
    _attempt(db_session, subject, 1, subject["mapping_ids"][0])          # selected
    _attempt(db_session, subject, 2, subject["mapping_ids"][1], started_at=BASE)  # in flight
    _written(db_session, subject, 3, subject["mapping_ids"][2])

    summary = client.get("/admin/collection-attempts").json()["summary"]
    assert summary["still_selected"] == 2
    assert summary["started"] == 2   # one in-flight, one written


def test_a_written_attempt_exposes_its_observation_id(client, db_session, subject):
    observation = PriceObservation(
        source_id=subject["source_id"],
        observed_at=BASE,
        price_type="sell",
        price_jpy=50,
        card_print_id=subject["print_id"],
        source_card_mapping_id=subject["mapping_ids"][0],
    )
    db_session.add(observation)
    db_session.commit()
    _written(
        db_session, subject, 1, subject["mapping_ids"][0], observation_id=observation.id
    )

    row = client.get("/admin/collection-attempts").json()["attempts"][0]
    assert row["price_observation_id"] == observation.id


def test_a_failed_attempt_exposes_no_observation_id(client, db_session, subject):
    _attempt(
        db_session, subject, 1, subject["mapping_ids"][0],
        status="operational_error", failure_stage="browser_launch",
        started_at=BASE, finished_at=BASE + timedelta(seconds=2),
    )

    row = client.get("/admin/collection-attempts").json()["attempts"][0]
    assert row["price_observation_id"] is None


# --- read-only -------------------------------------------------------------


def test_the_surface_is_read_only(client, db_session, subject):
    """No mutation route exists. Attempt rows are written solely by the
    collector services; an admin surface that could edit them would destroy
    the only property that makes them worth keeping."""
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/admin/collection-attempts")
        assert response.status_code == 405, f"{method.upper()} should not be routed"


def test_listing_does_not_change_any_row(client, db_session, subject):
    _written(db_session, subject, 1, subject["mapping_ids"][0])
    before = client.get("/admin/collection-attempts").json()["attempts"]

    client.get("/admin/collection-attempts", params={"status": "written"})
    client.get("/admin/collection-attempts", params={"limit": 1})

    after = client.get("/admin/collection-attempts").json()["attempts"]
    assert before == after
    assert db_session.query(SourceCollectionAttempt).count() == 1
