"""Forward publication against mock data, using the real receipt gate and replay."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, update

from app import market_value_publisher as publisher
from app import market_value_writer as recovery
from app.models import MarketIndexSnapshot
from app.models.job_lock import JobLock
from app.models.market_index_snapshot_completion import MarketIndexSnapshotCompletion
from app.models.market_value_membership import (
    MarketValueMembership,
    MarketValueMembershipPrint,
    MarketValueMembershipRelease,
)
from app.models.market_value_point import MarketValuePoint
from app.services import market_value_replay
from app.services.market_value_read import get_market_value
from tests._market_value_publication_helpers import (
    D25,
    D26,
    D27,
    D28,
    D29,
    archive_state,
    receipt,
    seed,
    stamp,
)


@pytest.fixture(autouse=True)
def no_current_prices(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("publication must never resolve live prices or fetch sources")

    monkeypatch.setattr(market_value_replay, "get_market_index_for_prints", forbidden)
    monkeypatch.setattr(
        market_value_replay, "select_snapshottable_print_ids", forbidden
    )


def publish(db, **kwargs):
    return publisher.run_publisher(db, mode="write", skip_lock=True, **kwargs)


def test_skips_receiptless_27_28_and_publishes_only_29_with_native_gap_rules(
    db_session,
):
    seed(db_session)
    before = archive_state(db_session)
    result = publish(db_session)
    assert result.plan.previous_as_of == D26
    assert result.plan.publication_dates == (D29,)
    assert result.inserted == 2  # Overall plus the one coded release.
    after = archive_state(db_session)
    for table in ("market_index_snapshots", "market_index_snapshot_completions"):
        assert after[table] == before[table]
    assert after["market_value_points"][:4] == before["market_value_points"]
    rows = list(
        db_session.scalars(
            select(MarketValuePoint).where(MarketValuePoint.point_date == D29)
        )
    )
    assert len(rows) == 2
    for row in rows:
        assert row.tracked_value_jpy == 16000
        assert row.prior_point_date == D26 and row.step_days == 3
        assert row.performance_factor == Decimal(1)
        assert row.step_publication_eligible is False
        assert row.methodology_version == 1
    assert set(db_session.scalars(select(MarketValuePoint.point_date))) == {
        D25,
        D26,
        D29,
    }
    response = get_market_value(db_session, window="all")
    assert response.as_of == D29 and response.tracked_value.value_jpy == 16000
    assert response.movement.available is False
    assert response.movement.reason == "insufficient_window_continuity"


def test_all_new_days_receiptless_writes_nothing(db_session):
    seed(db_session, receipt_days=())
    before = archive_state(db_session)
    result = publish(db_session)
    assert result.inserted == 0 and result.plan.publication_dates == ()
    assert archive_state(db_session) == before


@pytest.mark.parametrize(
    "column,value",
    [
        ("snapshot_content_digest", "0" * 64),
        ("selected_print_ids_digest", "f" * 64),
    ],
)
def test_invalid_receipt_aborts_without_any_changes(db_session, column, value):
    seed(db_session)
    db_session.execute(update(MarketIndexSnapshotCompletion).values({column: value}))
    db_session.commit()
    before = archive_state(db_session)
    with pytest.raises(publisher.WriterAbort, match="invalid snapshot completion"):
        publish(db_session)
    assert archive_state(db_session) == before


@pytest.mark.parametrize("explicit_date", [None, D29])
def test_same_day_retry_verifies_and_changes_nothing(db_session, explicit_date):
    seed(db_session)
    publish(db_session)
    before = archive_state(db_session)
    result = publish(db_session, publication_date=explicit_date)
    assert result.inserted == 0 and result.plan.new_drafts == ()
    assert result.plan.existing_verified == 6
    assert len(result.plan.receipts) == 1 and result.plan.receipts[0].valid
    assert archive_state(db_session) == before


def test_multiple_receipt_dates_are_ordered_and_do_not_invent_27(db_session):
    seed(db_session, receipt_days=(D29, D28))
    result = publish(db_session)
    assert result.plan.publication_dates == (D28, D29) and result.inserted == 4
    assert set(db_session.scalars(select(MarketValuePoint.point_date))) == {
        D25,
        D26,
        D28,
        D29,
    }
    rows = {
        r.point_date: r
        for r in db_session.scalars(
            select(MarketValuePoint).where(MarketValuePoint.scope_kind == "overall")
        )
    }
    assert rows[D28].prior_point_date == D26 and rows[D28].step_days == 2
    assert rows[D29].prior_point_date == D28 and rows[D29].step_days == 1


def test_population_mismatch_fails_before_writing(db_session):
    seed(db_session)
    db_session.execute(
        delete(MarketIndexSnapshot).where(
            MarketIndexSnapshot.snapshot_date == D29,
            MarketIndexSnapshot.card_print_id == 4,
        )
    )
    db_session.commit()
    before = archive_state(db_session)
    with pytest.raises(publisher.WriterAbort, match="row_count_mismatch"):
        publish(db_session)
    assert archive_state(db_session) == before


def test_active_producer_refuses_even_with_expired_lease(db_session):
    seed(db_session)
    db_session.execute(
        update(JobLock)
        .where(JobLock.lock_name == "market_index_snapshot")
        .values(status="active")
    )
    db_session.commit()
    before = archive_state(db_session)
    with pytest.raises(publisher.WriterAbort, match="snapshot_in_progress"):
        publish(db_session)
    assert archive_state(db_session) == before


def test_recovery_replay_still_includes_receiptless_archive_dates(db_session):
    seed(db_session, receipt_days=())
    result = recovery.run_writer(db_session, mode="write", through=D29, skip_lock=True)
    assert result.inserted == 6
    assert set(db_session.scalars(select(MarketValuePoint.point_date))) == {
        D25,
        D26,
        D27,
        D28,
        D29,
    }


@pytest.mark.parametrize("day", [D27, D28, date(2026, 9, 30), D26])
def test_date_specific_mode_rejects_receiptless_dates_including_legacy_published(
    db_session, day
):
    seed(db_session)
    before = archive_state(db_session)
    with pytest.raises(publisher.WriterAbort, match="receipt_missing"):
        publish(db_session, publication_date=day)
    assert archive_state(db_session) == before


def test_explicit_date_publishes_only_that_date_and_never_later_backfills(db_session):
    seed(db_session, receipt_days=(D28, D29))
    result = publish(db_session, publication_date=D29)
    assert result.plan.publication_dates == (D29,)
    before = archive_state(db_session)
    with pytest.raises(publisher.WriterAbort, match="no backfill"):
        publish(db_session, publication_date=D28)
    assert publish(db_session).inserted == 0
    assert archive_state(db_session) == before


def test_invalid_later_receipt_prevents_earlier_valid_date_being_partially_written(
    db_session,
):
    seed(db_session, receipt_days=(D28, D29))
    db_session.execute(
        update(MarketIndexSnapshotCompletion)
        .where(MarketIndexSnapshotCompletion.snapshot_date == D29)
        .values(snapshot_content_digest="0" * 64)
    )
    db_session.commit()
    before = archive_state(db_session)
    with pytest.raises(publisher.WriterAbort, match="invalid snapshot completion"):
        publish(db_session)
    assert archive_state(db_session) == before


@pytest.mark.parametrize("corruption", ["value", "missing_scope", "frozen_membership"])
def test_historical_prefix_must_reproduce_exactly_without_repair(
    db_session, corruption
):
    seed(db_session)
    if corruption == "value":
        db_session.execute(
            update(MarketValuePoint)
            .where(MarketValuePoint.point_date == D26)
            .values(tracked_value_jpy=999999)
        )
    elif corruption == "missing_scope":
        db_session.execute(
            delete(MarketValuePoint).where(
                MarketValuePoint.point_date == D26,
                MarketValuePoint.scope_kind == "release",
            )
        )
    else:
        # The ledger a published day is checked against has been altered.
        db_session.execute(
            delete(MarketValueMembershipPrint).where(
                MarketValueMembershipPrint.card_print_id == 1
            )
        )
    db_session.commit()
    before = archive_state(db_session)
    with pytest.raises(
        publisher.WriterAbort,
        match="does not match its rows" if corruption == "frozen_membership" else "history conflicts",
    ):
        publish(db_session)
    assert archive_state(db_session) == before


def test_changed_previously_published_receipt_fails_retry(db_session):
    seed(db_session)
    publish(db_session)
    db_session.execute(
        update(MarketIndexSnapshotCompletion).values(snapshot_content_digest="0" * 64)
    )
    db_session.commit()
    before = archive_state(db_session)
    with pytest.raises(publisher.WriterAbort, match="invalid snapshot completion"):
        publish(db_session)
    assert archive_state(db_session) == before


def test_empty_history_can_start_only_at_receipt_backed_date(db_session):
    seed(db_session, published=False)
    result = publish(db_session)
    assert result.plan.previous_as_of is None and result.inserted == 2
    assert set(db_session.scalars(select(MarketValuePoint.point_date))) == {D29}


def test_forward_replay_sql_never_loads_receiptless_unpublished_days(
    db_session, monkeypatch
):
    seed(db_session)
    real = market_value_replay._load_archive_rows
    calls = []

    def observing(db, **kwargs):
        rows = real(db, **kwargs)
        calls.append((kwargs, set(r.snapshot_date for r in rows)))
        return rows

    monkeypatch.setattr(market_value_replay, "_load_archive_rows", observing)
    publisher.run_publisher(db_session, mode="dry-run")
    assert calls == [
        ({"archive_dates": (D25, D26, D29), "live_catalogue": False}, {D25, D26, D29})
    ]


def test_dry_run_does_not_acquire_locks_or_write_rows(db_session, monkeypatch):
    seed(db_session)

    def forbidden(*args, **kwargs):
        pytest.fail("read-only plan acquired a job lock")

    monkeypatch.setattr(publisher, "with_job_lock", forbidden)
    before = archive_state(db_session)
    result = publisher.run_publisher(db_session, mode="dry-run")
    assert result.inserted == 0 and len(result.plan.new_drafts) == 2
    assert archive_state(db_session) == before


def test_publisher_requires_a_fresh_transaction(db_session):
    seed(db_session)
    db_session.execute(select(MarketValuePoint.id))
    with pytest.raises(publisher.WriterAbort, match="fresh transaction"):
        publish(db_session)


def test_normal_cli_has_no_through_and_recovery_write_requires_acknowledgement(capsys):
    with pytest.raises(SystemExit) as exc:
        publisher.main(["--write", "--through", str(D29)])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        recovery.main(["--write", "--through", str(D29)])
    assert exc.value.code == 2
    assert "historical writes require --replay" in capsys.readouterr().err


def test_cli_dry_run_reports_dates_and_prefix(db_session, monkeypatch, capsys):
    seed(db_session)
    monkeypatch.setattr(publisher, "SessionLocal", lambda: db_session)
    assert publisher.main(["--dry-run", "--date", str(D29)]) == 0
    output = capsys.readouterr().out
    assert "publication_dates: 2026-09-29" in output
    assert "existing_verified: 4" in output
    assert "planned_new_points: 2" in output and "inserted: 0" in output


# Owner plan A (2026-10-28): each published day keeps the membership it was
# published with; a catalogue import never makes published history "mismatch".


def _import_release(db, *, release_id=2, code="EB-05", print_ids=(5, 6), days=(D27,)):
    """A catalogue import after D26 was published: a new coded release with new
    prints, and their archive rows on `days`."""
    from datetime import datetime, timedelta, timezone

    from app.models import CanonicalCard, CardPrint, ReleaseProduct

    later = datetime.now(timezone.utc) + timedelta(days=1)  # after every stored point
    db.add(
        ReleaseProduct(
            id=release_id,
            source_catalogue="bandai_jp",
            official_code=code,
            display_name=f"Imported {code}",
            first_seen_name=f"Imported {code}",
            source_series_id=f"import-{release_id}",
            source_url=f"https://example.invalid/{release_id}",
            verification_status="verified",
        )
    )
    for pid in print_ids:
        db.add(CanonicalCard(id=pid, card_code=f"EB05-{pid:03}", name_en=f"New {pid}", card_type="CHARACTER"))
    db.flush()
    for pid in print_ids:
        db.add(
            CardPrint(
                id=pid,
                canonical_card_id=pid,
                language="jp",
                release_product_id=release_id,
                artwork_key="b" * 64,
                official_asset_variant="base",
                verification_status="verified",
                is_active=True,
                created_at=later,
            )
        )
        for day in days:
            db.add(
                MarketIndexSnapshot(
                    card_print_id=pid,
                    snapshot_date=day,
                    calculated_at=stamp(day),
                    index_value_jpy=pid * 100,
                    calculation_method="median",
                    source_count=1,
                    coverage_status="full",
                    confidence="high",
                    index_version=3,
                    source_semantics_version=2,
                    provenance={
                        "source_values": [
                            {
                                "source": "yuyutei",
                                "reference_type": "retail_ask",
                                "contributes_to_index": True,
                                "value_jpy": pid * 100,
                            }
                        ],
                        "auxiliary_values": [],
                    },
                )
            )
    db.commit()


def _points(db, day):
    return {
        row.release_product_id: row
        for row in db.scalars(select(MarketValuePoint).where(MarketValuePoint.point_date == day))
    }


def test_an_import_after_publication_publishes_the_next_day_with_its_own_frozen_membership(db_session):
    seed(db_session, receipt_days=())
    history = archive_state(db_session)["market_value_points"]
    legacy = db_session.scalar(select(MarketValuePoint.membership_revision).limit(1))
    _import_release(db_session)
    receipt(db_session, D27)
    result = publish(db_session)
    assert result.plan.publication_dates == (D27,) and result.inserted == 3
    assert archive_state(db_session)["market_value_points"][:4] == history  # untouched
    new = _points(db_session, D27)
    assert set(new) == {None, 1, 2}
    revision = new[None].membership_revision
    assert revision.startswith("card-print-release-coded-v2:") and revision != legacy
    assert {row.membership_revision for row in new.values()} == {revision}
    # New prints count from the day they arrive; the new release starts there.
    assert new[None].total_physical_print_count == 6
    assert new[2].prior_point_date is None and new[2].total_physical_print_count == 2
    # The unchanged release keeps comparing like with like.
    assert "membership_revision_changed" not in (new[1].publication_reasons or "")
    assert (new[1].prior_point_date, new[1].total_physical_print_count) == (D26, 4)
    frozen = {
        row.revision: row.origin for row in db_session.scalars(select(MarketValueMembership))
    }
    assert frozen == {legacy: "recovery", revision: "publication"}
    db_session.rollback()
    assert publish(db_session).inserted == 0  # an identical retry verifies and adds nothing


def test_a_release_whose_own_prints_change_starts_a_new_segment(db_session):
    from app.models import CardPrint

    seed(db_session, receipt_days=())
    db_session.get(CardPrint, 4).is_active = False
    db_session.commit()
    receipt(db_session, D27)
    publish(db_session)
    new = _points(db_session, D27)
    assert "membership_revision_changed" in new[1].publication_reasons
    assert new[1].total_physical_print_count == 3 and new[None].total_physical_print_count == 3


def test_a_published_day_without_a_frozen_membership_is_refused(db_session):
    seed(db_session, receipt_days=(D29,))
    for model in (MarketValueMembershipPrint, MarketValueMembershipRelease, MarketValueMembership):
        db_session.execute(delete(model))
    db_session.commit()
    before = archive_state(db_session)
    with pytest.raises(publisher.WriterAbort, match="membership_not_frozen"):
        publish(db_session)
    assert archive_state(db_session) == before


def test_dry_run_reports_the_membership_it_would_freeze_and_writes_nothing(db_session):
    seed(db_session, receipt_days=())
    _import_release(db_session)
    receipt(db_session, D27)
    result = publisher.run_publisher(db_session, mode="dry-run")
    lines = "\n".join(result.report_lines())
    assert "new_membership: card-print-release-coded-v2:" in lines and "prints=6 coded_releases=2" in lines
    assert db_session.scalar(select(func.count()).select_from(MarketValueMembership)) == 1


def test_legacy_membership_is_rebuilt_only_when_it_hashes_to_the_stored_revision(db_session):
    from app.models import CardPrint
    from app.services import market_value_membership as membership

    seed(db_session, receipt_days=())
    legacy = db_session.scalar(select(MarketValuePoint.membership_revision).limit(1))
    stored = membership.load_membership(db_session, legacy)
    for model in (MarketValueMembershipPrint, MarketValueMembershipRelease, MarketValueMembership):
        db_session.execute(delete(model))
    db_session.commit()
    _import_release(db_session)  # created after the publication: left out of the rebuild
    rebuilt = membership.rebuild_legacy_membership(db_session, legacy)
    assert rebuilt.ok and rebuilt.membership == stored
    assert rebuilt.facts["digest_matches"] and rebuilt.facts["candidate_prints"] == 4
    db_session.get(CardPrint, 1).is_active = False  # a change the rebuild cannot undo
    db_session.commit()
    refused = membership.rebuild_legacy_membership(db_session, legacy)
    assert not refused.ok and refused.facts["digest_matches"] is False


def test_the_legacy_freeze_runbook_plan_unblocks_publication(db_session):
    """Pre-ledger history (no frozen membership): the freeze plan rebuilds it exactly,
    the apply freezes only the approved plan, then the next day publishes."""
    from app.services import market_value_membership as membership

    seed(db_session, receipt_days=())
    for model in (MarketValueMembershipPrint, MarketValueMembershipRelease, MarketValueMembership):
        db_session.execute(delete(model))
    db_session.commit()
    _import_release(db_session)
    receipt(db_session, D27)
    with pytest.raises(publisher.WriterAbort, match="membership_not_frozen"):
        publish(db_session)
    plan, problems, facts = membership.legacy_freeze_plan(db_session)
    assert problems == [] and facts["unfrozen"] == 1 and len(plan["memberships"]) == 1
    assert plan["memberships"][0]["prints"] == 4
    with pytest.raises(membership.MembershipError, match="differs"):
        membership.apply_legacy_freeze(db_session, {"memberships": []})
    db_session.rollback()
    assert membership.apply_legacy_freeze(db_session, plan) == [plan["memberships"][0]["revision"]]
    db_session.commit()
    assert membership.legacy_freeze_plan(db_session)[1] == ["every stored revision already has a frozen membership"]
    db_session.rollback()
    assert publish(db_session).inserted == 3


def test_a_recovery_write_refuses_without_the_membership_ledger(db_session, monkeypatch):
    """Every stored point must name a frozen membership: before the ledger's
    migration a recovery write refuses instead of writing unfrozen points."""
    from app.services import market_value_membership as membership

    seed(db_session, receipt_days=(), published=False)
    monkeypatch.setattr(membership, "schema_present", lambda _db: False)
    with pytest.raises(recovery.WriterAbort, match="membership schema is absent"):
        recovery.run_writer(db_session, mode="write", through=D26, skip_lock=True)
    assert db_session.scalar(select(func.count()).select_from(MarketValuePoint)) == 0
