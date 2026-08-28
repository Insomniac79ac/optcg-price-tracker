"""The reparse job's safety contract, made executable.

The job rewrites stored rows, so the tests that matter are the ones about what
it REFUSES and what it leaves alone. A reparse that quietly widened its scope,
touched source evidence, or half-applied a batch would look like success in
every happy-path test, which is why most of what follows is negative.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from worker.jobs.reparse_snkrdunk_candidates import (
    CONFIRM_PHRASE,
    DERIVED_FIELDS,
    ReparseError,
    apply_reparse,
    plan_reparse,
)
from worker.models import Base, SnkrdunkCandidate, SnkrdunkDiscoveryRun

# Verbatim run-1 titles. The EB-01 pair is the case the job exists for: the
# alias resolves the label today and did not when the row was written.
EB_TITLE = "Charlotte Compote C [EB01-055] (Extra Booster Memorial Collection)"
OP_TITLE = "Usopp R [OP01-004] (Booster Pack ROMANCE DAWN)"
PCC_TITLE = "Jimbe C Parallel [ST01-005] (Premium Card Collection 25th Anniversary Edition)"


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def run(db):
    row = SnkrdunkDiscoveryRun(seed_url="https://snkrdunk.com/", status="completed")
    db.add(row)
    db.flush()
    return row


def _candidate(db, run, *, title, url, stale=True, **kw):
    """A row as run 1 left it: correct source evidence, stale derivation."""
    row = SnkrdunkCandidate(
        source_url=url,
        discovery_run_id=run.id,
        title=title,
        image_url=kw.pop("image_url", None),
        price_jpy=kw.pop("price_jpy", 1234),
        listing_count=kw.pop("listing_count", 3),
        condition_label=kw.pop("condition_label", "near mint"),
        raw_text=kw.pop("raw_text", title),
        match_status=kw.pop("match_status", "unmatched"),
        detected_card_code=kw.pop("detected_card_code", None if stale else "EB01-055"),
        detected_set_code=kw.pop("detected_set_code", None),
        **kw,
    )
    db.add(row)
    db.flush()
    return row


# --- scope ------------------------------------------------------------------


def test_an_unscoped_reparse_is_refused(db):
    """The failure this guards is a fat-fingered invocation rewriting every
    candidate in the database. There is no default scope."""
    with pytest.raises(ReparseError, match="Refusing an unscoped reparse"):
        plan_reparse(db)


def test_a_run_scope_covers_only_that_run(db, run):
    other = SnkrdunkDiscoveryRun(seed_url="https://snkrdunk.com/2", status="completed")
    db.add(other)
    db.flush()
    mine = _candidate(db, run, title=EB_TITLE, url="https://snkrdunk.com/a")
    _candidate(db, other, title=EB_TITLE, url="https://snkrdunk.com/b")

    report = plan_reparse(db, discovery_run_id=run.id)
    assert [p.candidate_id for p in report.plans] == [mine.id]


def test_an_id_scope_covers_only_those_ids(db, run):
    a = _candidate(db, run, title=EB_TITLE, url="https://snkrdunk.com/a")
    _candidate(db, run, title=OP_TITLE, url="https://snkrdunk.com/b")

    report = plan_reparse(db, candidate_ids=[a.id])
    assert [p.candidate_id for p in report.plans] == [a.id]


def test_an_unknown_candidate_id_is_refused_before_anything_is_planned(db, run):
    a = _candidate(db, run, title=EB_TITLE, url="https://snkrdunk.com/a")
    with pytest.raises(ReparseError, match="do not exist"):
        plan_reparse(db, candidate_ids=[a.id, 999_999])


# --- what it re-derives -----------------------------------------------------


def test_a_stale_row_gains_the_product_code_its_label_now_resolves_to(db, run):
    """The whole point. The row's title never changed; the alias table did."""
    row = _candidate(db, run, title=EB_TITLE, url="https://snkrdunk.com/a")
    assert row.detected_set_code is None

    report = plan_reparse(db, discovery_run_id=run.id)
    plan = report.plans[0]
    assert plan.after["detected_set_code"] == "EB-01"
    assert plan.after["detected_card_code"] == "EB01-055"
    assert "detected_set_code" in plan.changed_fields


def test_an_unresolvable_label_stays_null(db, run):
    """Reparsing is not an excuse to resolve what the alias table refuses."""
    _candidate(db, run, title=PCC_TITLE, url="https://snkrdunk.com/a")
    plan = plan_reparse(db, discovery_run_id=run.id).plans[0]
    assert plan.after["detected_set_code"] is None
    assert plan.after["detected_card_code"] == "ST01-005"


def test_a_row_already_carrying_the_current_derivation_is_unchanged(db, run):
    _candidate(
        db,
        run,
        title=OP_TITLE,
        url="https://snkrdunk.com/a",
        detected_card_code="OP01-004",
        detected_set_code="OP-01",
        detected_rarity="R",
        normalized_title="usopp r op01 004 booster pack romance dawn",
    )
    report = plan_reparse(db, discovery_run_id=run.id)
    plan = report.plans[0]
    assert plan.changed_fields == [] or "detected_set_code" not in plan.changed_fields
    assert plan.after["detected_set_code"] == "OP-01"


# --- what it must never touch ----------------------------------------------


def test_source_evidence_and_review_state_survive_an_apply(db, run):
    """The re-derivation READS the source evidence. Rewriting it would destroy
    the input and make the next reparse a reading of this job's output."""
    row = _candidate(
        db,
        run,
        title=EB_TITLE,
        url="https://snkrdunk.com/a",
        image_url="https://cdn.snkrdunk.com/x/TCG-OPC-EB01-055.webp",
        price_jpy=4321,
        listing_count=7,
        condition_label="near mint",
        raw_text="raw text as stored",
    )
    before = (
        row.source_url, row.title, row.image_url, row.price_jpy, row.listing_count,
        row.condition_label, row.raw_text, row.discovery_run_id,
        row.match_status, row.matched_card_id,
    )

    apply_reparse(db, discovery_run_id=run.id, confirm=CONFIRM_PHRASE)

    assert (
        row.source_url, row.title, row.image_url, row.price_jpy, row.listing_count,
        row.condition_label, row.raw_text, row.discovery_run_id,
        row.match_status, row.matched_card_id,
    ) == before
    assert row.detected_set_code == "EB-01"


@pytest.mark.parametrize("status", ["matched", "suggested", "ambiguous", "rejected"])
def test_a_row_that_has_progressed_past_unmatched_is_refused_not_skipped(db, run, status):
    """A stale row someone has already acted on is a fact the operator needs
    to see, so it is reported as a refusal rather than passed over."""
    row = _candidate(db, run, title=EB_TITLE, url="https://snkrdunk.com/a",
                     match_status=status)
    report = apply_reparse(db, discovery_run_id=run.id, confirm=CONFIRM_PHRASE)

    assert len(report.refused) == 1
    assert report.refused[0].candidate_id == row.id
    assert status in report.refused[0].refused_reason
    assert row.detected_set_code is None  # untouched
    assert report.writes == 0


def test_a_refused_row_offers_no_changes(db, run):
    _candidate(db, run, title=EB_TITLE, url="https://snkrdunk.com/a",
               match_status="matched")
    plan = plan_reparse(db, discovery_run_id=run.id).plans[0]
    assert plan.refused
    assert plan.changed_fields == []
    assert plan.after is None


# --- apply gating and transactionality --------------------------------------


def test_planning_is_the_default_and_writes_nothing(db, run):
    row = _candidate(db, run, title=EB_TITLE, url="https://snkrdunk.com/a")
    report = plan_reparse(db, discovery_run_id=run.id)
    assert report.applied is False
    assert report.writes == 0
    assert row.detected_set_code is None


@pytest.mark.parametrize("confirm", [None, "", "yes", "Reparse Candidates", "reparse candidate"])
def test_apply_without_the_exact_confirmation_phrase_is_refused(db, run, confirm):
    row = _candidate(db, run, title=EB_TITLE, url="https://snkrdunk.com/a")
    with pytest.raises(ReparseError, match="confirmation phrase"):
        apply_reparse(db, discovery_run_id=run.id, confirm=confirm)
    assert row.detected_set_code is None


def test_a_parse_failure_abandons_the_whole_batch(db, run, monkeypatch):
    """Rows are re-derived in full before any field is set, so a bad row late
    in the batch cannot leave the early rows rewritten."""
    good = _candidate(db, run, title=EB_TITLE, url="https://snkrdunk.com/a")
    bad = _candidate(db, run, title=OP_TITLE, url="https://snkrdunk.com/zzz")

    import worker.jobs.reparse_snkrdunk_candidates as mod

    real = mod.evidence_from_listing

    def exploding(source_url, title, image_url):
        if source_url == bad.source_url:
            raise ValueError("boom")
        return real(source_url, title, image_url)

    monkeypatch.setattr(mod, "evidence_from_listing", exploding)

    with pytest.raises(ReparseError, match="batch was abandoned"):
        apply_reparse(db, discovery_run_id=run.id, confirm=CONFIRM_PHRASE)

    db.rollback()
    assert good.detected_set_code is None


# --- idempotency ------------------------------------------------------------


def test_a_second_apply_writes_nothing(db, run):
    """Same rules, same stored evidence, so the second pass has nothing to do.
    This is what makes the job safe to re-run without thinking about it."""
    _candidate(db, run, title=EB_TITLE, url="https://snkrdunk.com/a")
    _candidate(db, run, title=OP_TITLE, url="https://snkrdunk.com/b")
    _candidate(db, run, title=PCC_TITLE, url="https://snkrdunk.com/c")

    first = apply_reparse(db, discovery_run_id=run.id, confirm=CONFIRM_PHRASE)
    assert first.writes > 0

    second = apply_reparse(db, discovery_run_id=run.id, confirm=CONFIRM_PHRASE)
    assert second.writes == 0
    assert second.changed == []
    assert len(second.unchanged) == len(second.plans)


def test_the_job_only_ever_writes_the_five_derived_fields(db, run):
    """A guard on the contract itself: if someone adds a sixth field to the
    write set, this fails until the docstring and the review agree."""
    assert DERIVED_FIELDS == (
        "normalized_title",
        "detected_card_code",
        "detected_set_code",
        "detected_rarity",
        "detected_variant",
    )
