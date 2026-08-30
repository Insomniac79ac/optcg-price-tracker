"""The purge job's safety contract, made executable.

Deletion is irreversible, so almost everything here is a refusal. The tests
that matter most are the ones proving the job will NOT delete: a row an
observation points at (its FK is ON DELETE SET NULL, so a careless delete
would silently blank real provenance), a row a human has touched, and any
genuine One Piece candidate at all.
"""

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from worker.db import Base
from worker.jobs.purge_non_target_candidates import (
    CONFIRM_PHRASE,
    PurgeError,
    apply_purge,
    plan_purge,
)
from worker.models import PriceObservation, SnkrdunkCandidate, Source, SourceCardMapping

CDN = "https://cdn.snkrdunk.com/upload_bg_removed/"
SVE = CDN + "SVE-TCG-bp08-117.webp?size=l"
OPC = CDN + "20220903005802-0.webp?size=l"
OPC_NEW = CDN + "OPC-EN-TCG-OP14-001-of.webp?size=l"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()


def _cand(db, id_, url, image, code, **kw):
    row = SnkrdunkCandidate(
        id=id_,
        source_url=url,
        title=f"Something [{code}] (A Product)",
        image_url=image,
        detected_card_code=code,
        match_status=kw.pop("match_status", "unmatched"),
        **kw,
    )
    db.add(row)
    db.flush()
    return row


# --- what it identifies -------------------------------------------------------


def test_only_non_target_candidates_are_identified(db):
    _cand(db, 1, "u/1", SVE, "BP08-117")
    _cand(db, 2, "u/2", OPC, "OP01-001")
    _cand(db, 3, "u/3", OPC_NEW, "OP14-001")
    report = plan_purge(db)
    assert [p.candidate_id for p in report.plans] == [1]
    assert report.plans[0].game == "Shadowverse Evolve"
    assert len(report.removable) == 1


def test_a_plan_deletes_nothing(db):
    _cand(db, 1, "u/1", SVE, "BP08-117")
    report = plan_purge(db)
    assert report.applied is False
    assert report.deletes == 0
    assert db.get(SnkrdunkCandidate, 1) is not None


def test_a_corpus_with_no_contamination_plans_nothing(db):
    _cand(db, 1, "u/1", OPC, "OP01-001")
    report = plan_purge(db)
    assert report.plans == []
    assert report.deletes == 0


# --- the id cross-check -------------------------------------------------------


def test_the_operators_ids_must_equal_the_predicates(db):
    _cand(db, 1, "u/1", SVE, "BP08-117")
    _cand(db, 2, "u/2", SVE, "BP08-116")
    assert len(plan_purge(db, [1, 2]).removable) == 2
    with pytest.raises(PurgeError, match="disagree"):
        plan_purge(db, [1])          # operator expects fewer
    with pytest.raises(PurgeError, match="disagree"):
        plan_purge(db, [1, 2, 3])    # operator expects a row the rule does not name


# --- relationship refusals ----------------------------------------------------


def test_a_candidate_an_observation_references_is_refused(db):
    """The FK is ON DELETE SET NULL, so deleting would succeed and silently
    blank the observation's provenance. It must be refused instead."""
    db.add(Source(id=1, name="snkrdunk", base_url="https://snkrdunk.com"))
    c = _cand(db, 1, "u/1", SVE, "BP08-117")
    db.add(PriceObservation(id=1, source_id=1, candidate_id=c.id, price_type="sell", price_jpy=100))
    db.flush()
    report = plan_purge(db)
    assert report.removable == []
    assert "price_observation" in report.refused[0].refused_reason
    with pytest.raises(PurgeError, match="may not be deleted"):
        apply_purge(db, confirm=CONFIRM_PHRASE)
    assert db.get(SnkrdunkCandidate, 1) is not None


def test_a_candidate_sharing_a_mapping_source_url_is_refused(db):
    db.add(Source(id=1, name="snkrdunk", base_url="https://snkrdunk.com"))
    db.add(SourceCardMapping(id=1, source_id=1, source_card_id="x1", source_url="u/1"))
    _cand(db, 1, "u/1", SVE, "BP08-117")
    db.flush()
    report = plan_purge(db)
    assert report.removable == []
    assert "source_card_mapping" in report.refused[0].refused_reason


@pytest.mark.parametrize("status", ["matched", "suggested", "ambiguous", "rejected"])
def test_a_candidate_a_human_has_acted_on_is_refused(db, status):
    _cand(db, 1, "u/1", SVE, "BP08-117", match_status=status)
    report = plan_purge(db)
    assert report.removable == []
    assert "match_status" in report.refused[0].refused_reason


def test_a_candidate_the_matcher_has_ranked_is_refused(db):
    """`best_match_card_id` is written by the api and is NOT mapped on the
    worker's model, so the guard has to read it with SQL. The column is added
    here because the worker's own schema omits it - which is exactly the
    condition under which an attribute-based guard would silently pass."""
    _cand(db, 1, "u/1", SVE, "BP08-117")
    db.execute(text("alter table snkrdunk_candidates add column best_match_card_id integer"))
    db.execute(text("update snkrdunk_candidates set best_match_card_id = 7 where id = 1"))
    report = plan_purge(db)
    assert report.removable == []
    assert "best_match_card_id is 7" in report.refused[0].refused_reason
    with pytest.raises(PurgeError, match="may not be deleted"):
        apply_purge(db, confirm=CONFIRM_PHRASE)
    assert db.get(SnkrdunkCandidate, 1) is not None


def test_one_refusal_aborts_the_whole_batch(db):
    """No partial deletes: a batch with a single unsafe row deletes nothing."""
    _cand(db, 1, "u/1", SVE, "BP08-117")
    _cand(db, 2, "u/2", SVE, "BP08-116", match_status="matched")
    with pytest.raises(PurgeError):
        apply_purge(db, confirm=CONFIRM_PHRASE)
    assert db.get(SnkrdunkCandidate, 1) is not None
    assert db.get(SnkrdunkCandidate, 2) is not None


# --- the confirmation guard ---------------------------------------------------


@pytest.mark.parametrize("confirm", [None, "", "purge", "PURGE NON-TARGET CANDIDATES", "yes"])
def test_apply_without_the_exact_phrase_refuses(db, confirm):
    _cand(db, 1, "u/1", SVE, "BP08-117")
    with pytest.raises(PurgeError, match="confirmation phrase"):
        apply_purge(db, confirm=confirm)
    assert db.get(SnkrdunkCandidate, 1) is not None


# --- applying -----------------------------------------------------------------


def test_apply_deletes_only_the_identified_rows(db):
    _cand(db, 1, "u/1", SVE, "BP08-117")
    _cand(db, 2, "u/2", OPC, "OP01-001")
    _cand(db, 3, "u/3", OPC_NEW, "OP14-001")
    report = apply_purge(db, confirm=CONFIRM_PHRASE)
    assert report.deletes == 1
    assert db.get(SnkrdunkCandidate, 1) is None
    assert db.get(SnkrdunkCandidate, 2) is not None
    assert db.get(SnkrdunkCandidate, 3) is not None


def test_a_second_apply_deletes_nothing(db):
    _cand(db, 1, "u/1", SVE, "BP08-117")
    assert apply_purge(db, confirm=CONFIRM_PHRASE).deletes == 1
    second = apply_purge(db, confirm=CONFIRM_PHRASE)
    assert second.deletes == 0
    assert second.plans == []


def test_the_evidence_file_captures_the_rows_before_deletion(db, tmp_path):
    _cand(db, 1, "u/1", SVE, "BP08-117")
    path = tmp_path / "removed.json"
    apply_purge(db, confirm=CONFIRM_PHRASE, evidence_file=str(path))
    rows = json.loads(path.read_text())
    assert len(rows) == 1
    assert rows[0]["id"] == 1
    assert rows[0]["detected_card_code"] == "BP08-117"
    assert rows[0]["source_url"] == "u/1"
    assert db.get(SnkrdunkCandidate, 1) is None


def test_the_report_names_the_exact_ids(db):
    _cand(db, 1, "u/1", SVE, "BP08-117")
    _cand(db, 5, "u/5", SVE, "BP08-116")
    data = plan_purge(db).as_dict()
    assert data["candidate_ids"] == [1, 5]
    assert data["games"] == {"Shadowverse Evolve": 2}
    assert data["applied"] is False and data["deletes"] == 0
