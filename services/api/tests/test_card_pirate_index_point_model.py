"""The CardPirateIndexPoint model, and the guarantees that are not about SQL.

The Postgres file next door proves what the constraints DO. This one proves
things a live engine cannot: that the persisted column set is exactly what
docs/card_pirate_index.md froze and nothing more, that the state the document
deliberately made derivable was not quietly stored anyway, and that no writer
capable of breaking the append-only contract has been introduced.

That last one is the point of the file. The carry is a self-reference, and its
acyclicity rests on a convention - "a fresh INSERT can only point at a row that
already exists, and nothing ever UPDATEs" - rather than on a schema guarantee.
A convention that nothing tests is a convention that quietly stops holding, so
it is tested here.
"""

import re
from pathlib import Path

import pytest
from sqlalchemy import inspect

import app.models as models
from app.models import CardPirateIndexPoint
from app.models.card_pirate_index_point import (
    BASE_VALUE,
    SCOPE_KINDS,
    UNPUBLISHABLE_INSUFFICIENT_CONSTITUENTS,
    UNPUBLISHABLE_MIXED_VERSION_DAY,
)

API_ROOT = Path(__file__).resolve().parents[1] / "app"

TABLE = "card_pirate_index_points"

# Exactly the columns section 8.4 froze, in declaration order.
EXPECTED_COLUMNS = [
    "id",
    "scope_kind",
    "scope_key",
    "methodology_version",
    "index_version",
    "source_semantics_version",
    "point_date",
    "index_value",
    "is_base",
    "carried_from_point_id",
    "prior_point_date",
    "step_days",
    "chain_link_log_return",
    "constituent_count",
    "eligible_print_count",
    "movers_up",
    "movers_down",
    "movers_flat",
    "capped_count",
    "unpublishable_reason",
    "calculated_at",
    "created_at",
]

EXPECTED_CHECKS = {
    "ck_cpi_points_carry_requires_base",
    "ck_cpi_points_carry_not_self",
    "ck_cpi_points_initial_base_is_base_value",
    "ck_cpi_points_scope_kind",
    "ck_cpi_points_scope_key_pairing",
    "ck_cpi_points_value_presence",
    "ck_cpi_points_base_has_value",
    "ck_cpi_points_base_has_no_step",
    "ck_cpi_points_step_requires_prior",
    "ck_cpi_points_step_days_positive",
    "ck_cpi_points_constituents_le_eligible",
    "ck_cpi_points_breadth_presence",
    "ck_cpi_points_movers_pairing",
    "ck_cpi_points_movers_sum",
    "ck_cpi_points_capped_le_constituents",
    "ck_cpi_points_counts_non_negative",
}


# --- registration -----------------------------------------------------------


def test_model_is_registered_and_exported():
    assert TABLE in models.Base.metadata.tables
    assert "CardPirateIndexPoint" in models.__all__
    assert models.CardPirateIndexPoint is CardPirateIndexPoint


def test_table_is_created_by_the_test_harness(db_session):
    """conftest builds every table from Base.metadata. If the composite
    self-referential foreign key were malformed, create_all would be where it
    surfaced."""
    names = inspect(db_session.get_bind()).get_table_names()
    assert TABLE in names


# --- the frozen column set --------------------------------------------------


def test_columns_are_exactly_what_the_methodology_froze():
    actual = [c.name for c in CardPirateIndexPoint.__table__.columns]
    assert actual == EXPECTED_COLUMNS


@pytest.mark.parametrize(
    "derivable",
    [
        # The initial/carried distinction IS carried_from_point_id's
        # nullability. Storing it again would create a column that can
        # contradict its own source of truth.
        "segment_base_kind",
        # One join away from carried_from_point_id.
        "carried_from_point_date",
        # index_value on the base row already IS the carried level, and the
        # foreign key proves it equals the source's.
        "segment_base_value",
        "boundary_from_level",
        # Per-constituent evidence lives in market_index_snapshots.provenance,
        # is immutable, and is replayable. Duplicating it costs ~660 B/point.
        "provenance",
        # v1 rejects percentile winsorization outright; the column is
        # capped_count and the rejected name must not reappear.
        "winsorized_count",
        # Segment membership is a contiguous run of equal version triples,
        # derived in one pass.
        "segment_id",
        "segment_index",
    ],
)
def test_derivable_state_was_not_persisted_anyway(derivable):
    assert derivable not in CardPirateIndexPoint.__table__.columns


def test_nullability_matches_the_contract():
    cols = CardPirateIndexPoint.__table__.columns
    required = {
        "id", "scope_kind", "scope_key", "methodology_version", "index_version",
        "source_semantics_version", "point_date", "is_base",
        "constituent_count", "eligible_print_count", "calculated_at", "created_at",
    }
    for name, column in cols.items():
        if name in required:
            assert not column.nullable, f"{name} must be NOT NULL"
        else:
            assert column.nullable, f"{name} must be nullable"


def test_index_value_is_exact_not_floating_point():
    """The level is chain-linked over hundreds of steps; a binary float would
    accumulate drift into a published number."""
    index_value = CardPirateIndexPoint.__table__.c.index_value
    assert index_value.type.precision == 12
    assert index_value.type.scale == 4
    step = CardPirateIndexPoint.__table__.c.chain_link_log_return
    assert step.type.precision == 18
    assert step.type.scale == 12


# --- constraints present in metadata ----------------------------------------


def test_every_frozen_check_constraint_is_declared():
    names = {
        c.name
        for c in CardPirateIndexPoint.__table__.constraints
        if c.name and c.name.startswith("ck_")
    }
    assert names == EXPECTED_CHECKS


def test_natural_key_is_scope_qualified_and_excludes_index_version():
    """index_version out of the key is deliberate: two rows for one day under
    two index_versions is an error, not a legal pair."""
    unique = {
        c.name: [col.name for col in c.columns]
        for c in CardPirateIndexPoint.__table__.constraints
        if c.name and c.name.startswith("uq_")
    }
    assert unique["uq_cpi_points_point"] == [
        "scope_kind", "scope_key", "methodology_version", "point_date"
    ]
    assert "index_version" not in unique["uq_cpi_points_point"]
    assert unique["uq_cpi_points_carry_target"] == [
        "id", "scope_kind", "scope_key", "index_value"
    ]


def test_carry_foreign_key_is_composite_self_referential_and_restricts():
    fks = list(CardPirateIndexPoint.__table__.foreign_key_constraints)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.name == "fk_cpi_points_carried_from"
    assert [c.name for c in fk.columns] == [
        "carried_from_point_id", "scope_kind", "scope_key", "index_value"
    ]
    assert [e.column.name for e in fk.elements] == [
        "id", "scope_kind", "scope_key", "index_value"
    ]
    # Same table on both sides.
    assert {e.column.table.name for e in fk.elements} == {TABLE}
    # RESTRICT on both, so the chain cannot be truncated and a carried-from
    # level cannot be rewritten.
    assert fk.ondelete == "RESTRICT"
    assert fk.onupdate == "RESTRICT"
    # NOT deferrable: a carried base can only reference a row that already
    # exists, which is what makes insertion order meaningful.
    assert not fk.deferrable


def test_no_extra_indexes_beyond_the_unique_constraints():
    assert CardPirateIndexPoint.__table__.indexes == set()


# --- module vocabulary ------------------------------------------------------


def test_module_constants_match_the_frozen_methodology():
    assert BASE_VALUE == 1000
    assert SCOPE_KINDS == ("overall", "set", "rarity")
    assert UNPUBLISHABLE_INSUFFICIENT_CONSTITUENTS == "insufficient_constituents"
    assert UNPUBLISHABLE_MIXED_VERSION_DAY == "mixed_version_day"


# --- the append-only convention ---------------------------------------------


def _python_sources():
    for path in API_ROOT.rglob("*.py"):
        yield path, path.read_text()


# Every module allowed to name this table, and why. Anything else appearing
# here is a new writer nobody reviewed - a route, a job, a scheduler - which
# is exactly what this list exists to catch. Extend it deliberately, with a
# reason, or not at all.
def _references_the_table(source: str) -> bool:
    """Does this module USE the table, as opposed to merely mentioning it?

    Checks executable code only - identifiers and string literals that are not
    docstrings are both meaningful, but comments and docstrings are not. Two
    false positives made this necessary rather than optional:

      * `CardPirateIndexPointOut`, the response DTO, CONTAINS the model's name
        as a substring while being a different class that never touches the
        ORM;
      * `schemas.py` names the table in a docstring explaining where the data
        comes from.

    Both would have been "fixed" by widening the allowlist, which would have
    quietly blunted the guard for every module after them. Matching on what
    the code does keeps it sharp.
    """
    import io
    import tokenize

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return TABLE in source or "CardPirateIndexPoint" in source

    docstring_positions = set()
    prev_meaningful = None
    for tok in tokens:
        if tok.type in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT,
                        tokenize.INDENT, tokenize.DEDENT):
            continue
        if tok.type == tokenize.STRING and prev_meaningful in (None, ":", ""):
            docstring_positions.add(tok.start)
        prev_meaningful = tok.string
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and tok.start in docstring_positions:
            continue
        if tok.type == tokenize.NAME and tok.string == "CardPirateIndexPoint":
            return True
        if tok.type == tokenize.STRING and TABLE in tok.string:
            return True
    return False


ALLOWED_REFERENCES = {
    # the model itself
    "models/card_pirate_index_point.py",
    # the package that re-exports it so Base.metadata sees it
    "models/__init__.py",
    # the estimator: names the table only in prose, never touches the ORM
    "services/card_pirate_index.py",
    # the sole writer - INSERT only, via ON CONFLICT DO NOTHING - and the
    # read-only verifier
    "services/card_pirate_index_replay.py",
    # the read path: SELECTs published points, runs no estimator, writes
    # nothing (its own suite proves the absence of every write verb)
    "services/card_pirate_index_read.py",
    # the daily job: reads the persisted head and the pre/post-write
    # fingerprint, and inserts only through card_pirate_index_replay. Its own
    # suite proves it has no UPDATE, no DELETE and exactly one commit.
    "card_pirate_index_writer.py",
}
# NOTE: api/analytics.py is deliberately NOT listed. The read route reaches the
# index through the read service and the response DTO, never through the ORM
# class or the table name, so it is not a reference at all. Listing it anyway
# would exempt it in advance from the write guard below - the day someone adds
# an INSERT there, the import that made it work would flip it to a reference
# and the guard must be free to catch that.


def test_only_reviewed_modules_reference_this_table():
    """No route, job or scheduler may reach the table.

    Superseded the stricter "nothing references it at all" form when the
    estimator and replay layers landed: those are the reviewed writers, and
    the guard that still earns its place is the allowlist. A cron, an API
    route or a frontend proxy appearing here fails this test.
    """
    offenders = []
    for path, source in _python_sources():
        relative = str(path.relative_to(API_ROOT))
        if relative in ALLOWED_REFERENCES:
            continue
        if _references_the_table(source):
            offenders.append(relative)
    assert offenders == [], (
        "the Card Pirate Index table is referenced by an unreviewed module: "
        f"{offenders}"
    )


def test_no_route_or_job_writes_points_yet():
    """Routes may READ the index; nothing outside the replay service may WRITE
    it, and no job or scheduler may touch it at all.

    Tightened when the read endpoint landed. The earlier form asserted that no
    `api/` module so much as NAMED the table, which was the right guard while
    the API tranche was still ahead of us and the wrong one the moment a
    read-only route existed. What still earns its place is the narrower claim:
    a route that INSERTs, UPDATEs or DELETEs a point - or any job, scheduler or
    Celery module reaching the table at all - is a tranche boundary crossed
    without review.
    """
    import re

    write_verbs = re.compile(
        r"\.add\(|\.add_all\(|\.delete\(|\.merge\(|"
        r"insert\s*\(\s*CardPirateIndexPoint|"
        r"update\s*\(\s*CardPirateIndexPoint|"
        r"delete\s*\(\s*CardPirateIndexPoint|"
        r"(?:INSERT|UPDATE|DELETE)\s+(?:INTO\s+)?card_pirate_index_points",
        re.IGNORECASE,
    )
    routes_that_write = []
    jobs_touching_at_all = []
    for path, source in _python_sources():
        relative = str(path.relative_to(API_ROOT))
        names_table = _references_the_table(source)
        if not names_table:
            continue
        if relative.startswith("api/") and write_verbs.search(source):
            routes_that_write.append(relative)
        if relative.startswith("snapshot_") or "celery" in relative or "worker" in relative:
            jobs_touching_at_all.append(relative)

    assert routes_that_write == [], f"a route writes the index: {routes_that_write}"
    assert jobs_touching_at_all == [], (
        f"a job or scheduler already touches the index: {jobs_touching_at_all}"
    )


def test_no_update_writer_exists_for_this_table():
    """The carry chain's acyclicity rests on there being no UPDATE path: a
    fresh INSERT can only point backwards at a row that already exists, so a
    cycle requires an UPDATE. No trigger defends this - the absence of a
    writer does, and that absence is what this asserts.

    Cycle detection itself belongs to the future --verify replay, which must
    reject a cycle and any carry whose target date is not strictly earlier
    than the carrying row's.
    """
    pattern = re.compile(
        r"update\s*\(\s*CardPirateIndexPoint|"
        r"UPDATE\s+card_pirate_index_points|"
        r"on_conflict_do_update",
        re.IGNORECASE,
    )
    offenders = [
        str(path.relative_to(API_ROOT))
        for path, source in _python_sources()
        if pattern.search(source)
    ]
    assert offenders == [], f"an UPDATE writer was introduced: {offenders}"


def test_table_is_not_prunable():
    """The replay/verify guarantee depends on market_index_snapshots never
    being pruned, and a pruned points table would destroy the published
    series. Neither belongs in the retention whitelist."""
    from app.services.data_retention import PRUNABLE_TABLES

    assert TABLE not in PRUNABLE_TABLES
    assert "market_index_snapshots" not in PRUNABLE_TABLES
