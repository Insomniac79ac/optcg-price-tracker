"""Operator behavior for the Market Value writer CLI.

SQLite keeps these command/reporting tests fast.  The transaction, lock, and
rollback guarantees are repeated against disposable PostgreSQL in
``test_market_value_writer_postgres.py``.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

import pytest
from sqlalchemy import func, select, update

from app import market_value_writer as writer
from app.models.market_value_point import MarketValuePoint
from app.services.market_value_persistence import persist_market_value_points
from app.services.market_value_replay import MarketValueReplayInput
from tests.test_market_value_persistence import D1, D2, D3, replay_fixture


def _bounded_fixture(through=None) -> MarketValueReplayInput:
    loaded = replay_fixture()
    dates = tuple(day for day in loaded.archive_dates if through is None or day <= through)
    return replace(
        loaded,
        archive_dates=dates,
        observations_by_date={day: loaded.observations_by_date[day] for day in dates},
        current_observations=(),
    )


@pytest.fixture
def replay_loader(monkeypatch):
    calls = []

    def load(_db, *, through=None, include_current=True):
        calls.append((through, include_current))
        return _bounded_fixture(through)

    monkeypatch.setattr(writer, "load_market_value_replay_input", load)
    return calls


def _count(db_session) -> int:
    return db_session.scalar(select(func.count()).select_from(MarketValuePoint))


def test_no_mode_refuses_and_prints_usage(capsys):
    with pytest.raises(SystemExit) as exc_info:
        writer.main([])
    assert exc_info.value.code == 2
    assert "one of the arguments --dry-run --verify --write is required" in (
        capsys.readouterr().err
    )


def test_invalid_through_date_refuses(capsys):
    with pytest.raises(SystemExit) as exc_info:
        writer.main(["--dry-run", "--through", "2026-09-31"])
    assert exc_info.value.code == 2
    assert "expected YYYY-MM-DD" in capsys.readouterr().err


def test_main_dry_run_reports_operator_evidence(
    db_session, replay_loader, monkeypatch, capsys
):
    monkeypatch.setattr(writer, "SessionLocal", lambda: db_session)
    assert writer.main(["--dry-run", "--through", str(D2)]) == 0
    output = capsys.readouterr().out
    assert "mode: dry-run" in output
    assert f"archive_cutoff: {D2}" in output
    assert "expected_points: 4" in output
    assert "inserted: 0" in output
    assert "existing: 0" in output
    assert "verified: 0" in output
    assert "overall_points: 2" in output
    assert "release_points: 2" in output
    assert "scope_count: 2" in output
    assert "first_date: 2026-09-24" in output
    assert "last_date: 2026-09-25" in output
    assert "membership_revision: current-corrected-card-print-release-v1:test" in output
    assert "methodology_version: 1" in output
    assert _count(db_session) == 0


def test_dry_run_on_empty_table_reports_complete_plan_and_writes_nothing(
    db_session, replay_loader
):
    result = writer.run_writer(db_session, mode="dry-run")

    assert result.ok
    assert result.plan.expected_points == 6
    assert result.plan.overall_points == 3
    assert result.plan.release_points == 3
    assert result.plan.scope_count == 2
    assert result.plan.first_date == D1
    assert result.plan.last_date == D3
    assert result.plan.to_insert == 6
    assert result.existing == 0
    assert result.inserted == 0
    assert _count(db_session) == 0
    assert replay_loader == [(None, False)]

    report = result.report_lines()
    assert "overall_points: 3" in report
    assert "release_points: 3" in report
    assert "scope_count: 2" in report
    assert "to_insert: 6" in report


def test_dry_run_with_identical_existing_rows_reports_present_not_inserted(
    db_session, replay_loader
):
    drafts = writer.build_market_value_point_drafts(_bounded_fixture())
    persist_market_value_points(db_session, drafts[:2])
    db_session.commit()

    result = writer.run_writer(db_session, mode="dry-run")

    assert result.ok
    assert result.existing == 2
    assert result.plan.to_insert == 4
    assert result.inserted == 0
    assert _count(db_session) == 2


def test_verify_exact_match_and_mismatch(db_session, replay_loader):
    drafts = writer.build_market_value_point_drafts(_bounded_fixture())
    persist_market_value_points(db_session, drafts)
    db_session.commit()

    exact = writer.run_writer(db_session, mode="verify")
    assert exact.ok
    assert (
        exact.verification.expected,
        exact.verification.persisted,
        exact.verification.verified,
    ) == (6, 6, 6)

    db_session.execute(
        update(MarketValuePoint)
        .where(
            MarketValuePoint.scope_kind == "overall",
            MarketValuePoint.point_date == D2,
        )
        .values(tracked_value_jpy=33001)
    )
    db_session.commit()

    mismatch = writer.run_writer(db_session, mode="verify")
    assert not mismatch.ok
    assert mismatch.verification.verified == 5
    assert len(mismatch.verification.mismatches) == 1
    assert mismatch.report_lines()[-1] == "mismatched: 1"


def test_write_initial_seed_and_idempotent_rerun(db_session, replay_loader):
    first = writer.run_writer(db_session, mode="write", skip_lock=True)
    assert first.ok
    assert (first.inserted, first.existing, first.verification.verified) == (6, 0, 6)
    assert _count(db_session) == 6

    second = writer.run_writer(db_session, mode="write", skip_lock=True)
    assert second.ok
    assert (second.inserted, second.existing, second.verification.verified) == (0, 6, 6)
    assert _count(db_session) == 6


def test_write_conflict_refuses_and_leaves_entire_table_unchanged(
    db_session, replay_loader
):
    drafts = writer.build_market_value_point_drafts(_bounded_fixture())
    conflicting = drafts[3]
    row = MarketValuePoint(**conflicting.values())
    row.tracked_value_jpy += 1
    db_session.add(row)
    db_session.commit()
    before = tuple(db_session.scalars(select(MarketValuePoint)))

    with pytest.raises(writer.WriterAbort, match="conflicts"):
        writer.run_writer(db_session, mode="write", skip_lock=True)

    after = tuple(db_session.scalars(select(MarketValuePoint)))
    assert len(before) == len(after) == 1
    assert after[0].id == before[0].id
    assert after[0].tracked_value_jpy == before[0].tracked_value_jpy


def test_through_cutoff_excludes_later_archive_dates(db_session, replay_loader):
    result = writer.run_writer(
        db_session, mode="write", through=D2, skip_lock=True
    )

    assert result.plan.expected_points == 4
    assert result.plan.overall_points == 2
    assert result.plan.release_points == 2
    assert result.plan.first_date == D1
    assert result.plan.last_date == D2
    assert set(db_session.scalars(select(MarketValuePoint.point_date))) == {D1, D2}
    assert D3 not in set(db_session.scalars(select(MarketValuePoint.point_date)))
    assert replay_loader == [(D2, False)]


def test_dry_run_and_verify_never_acquire_writer_lock(
    db_session, replay_loader, monkeypatch
):
    @contextmanager
    def forbidden_lock(*_args, **_kwargs):
        raise AssertionError("read-only mode attempted to acquire a writer lock")
        yield

    monkeypatch.setattr(writer, "with_job_lock", forbidden_lock)
    assert writer.run_writer(db_session, mode="dry-run").ok
    verify = writer.run_writer(db_session, mode="verify")
    assert not verify.ok
    assert len(verify.verification.missing_keys) == 6


def test_write_uses_market_value_specific_lock(db_session, replay_loader, monkeypatch):
    seen = []

    @contextmanager
    def recording_lock(name, **kwargs):
        seen.append((name, kwargs))
        yield "owner"

    monkeypatch.setattr(writer, "with_job_lock", recording_lock)
    result = writer.run_writer(db_session, mode="write", through=D2)
    assert result.ok
    assert seen == [
        (
            "market_value_writer",
            {"metadata": {"mode": "write", "through": str(D2)}},
        )
    ]


def test_duplicate_replay_keys_refuse_before_persistence(
    db_session, replay_loader, monkeypatch
):
    drafts = writer.build_market_value_point_drafts(_bounded_fixture())
    monkeypatch.setattr(
        writer, "build_market_value_point_drafts", lambda _loaded: drafts + (drafts[0],)
    )
    with pytest.raises(writer.WriterAbort, match="duplicate natural keys"):
        writer.run_writer(db_session, mode="dry-run")
    assert _count(db_session) == 0


def test_invalid_release_identity_refuses_before_persistence(
    db_session, replay_loader, monkeypatch
):
    loaded = _bounded_fixture()
    invalid = replace(
        loaded,
        coded_releases=(replace(loaded.coded_releases[0], official_code=" "),),
    )
    monkeypatch.setattr(
        writer,
        "load_market_value_replay_input",
        lambda _db, **_kwargs: invalid,
    )
    with pytest.raises(writer.WriterAbort, match="release identity is invalid"):
        writer.run_writer(db_session, mode="write", skip_lock=True)
    assert _count(db_session) == 0


def test_unexpected_methodology_refuses_write(db_session, replay_loader):
    draft = writer.build_market_value_point_drafts(_bounded_fixture())[0]
    values = draft.values()
    values["methodology_version"] = 99
    db_session.add(MarketValuePoint(**values))
    db_session.commit()

    with pytest.raises(writer.WriterAbort, match="unsupported methodology version"):
        writer.run_writer(db_session, mode="write", skip_lock=True)
    assert _count(db_session) == 1


def test_missing_schema_refuses_write(db_session, replay_loader):
    MarketValuePoint.__table__.drop(db_session.get_bind())
    with pytest.raises(writer.WriterAbort, match="market_value_points is absent"):
        writer.run_writer(db_session, mode="write", skip_lock=True)
