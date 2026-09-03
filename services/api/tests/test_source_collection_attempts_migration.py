"""The b8e3f1a70d95 source_collection_attempts migration.

Same technique as test_promotion_state_migration.py - op.* is replaced by a
recorder instead of executing DDL, so no live Postgres is needed, and anything
the migration calls that is NOT recorded raises AttributeError rather than
passing silently.

Two things are asserted that a schema test would not normally bother with:

  * The migration touches no existing row. This table exists because failure
    left no evidence; a migration that quietly backfilled it from
    price_observations would manufacture the very history it is supposed to
    start recording honestly.
  * The migration and app.models.source_collection_attempt agree column for
    column. They are two independent declarations of one table, and every
    other assertion in the suite runs against the model via
    Base.metadata.create_all - so a migration that disagreed with the model
    would otherwise be caught nowhere.
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from app.models import SourceCollectionAttempt
from app.models.source_collection_attempt import FAILURE_STAGES, STATUSES

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "b8e3f1a70d95_add_source_collection_attempts.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("attempts_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _capture(direction: str) -> dict:
    module = _load_migration()
    captured = {
        "create_table": [],
        "drop_table": [],
        "create_index": [],
        "drop_index": [],
        "execute": [],
        "bulk_insert": [],
        "get_bind": [],
    }

    module.op.create_table = lambda name, *cols, **kw: captured["create_table"].append((name, cols))
    module.op.drop_table = lambda name, **kw: captured["drop_table"].append(name)
    module.op.create_index = lambda name, table, cols, **kw: captured["create_index"].append(
        (name, table, cols)
    )
    module.op.drop_index = lambda name, **kw: captured["drop_index"].append(name)
    # The three routes a data migration could take to existing rows.
    module.op.execute = lambda *a, **kw: captured["execute"].append(a)
    module.op.bulk_insert = lambda *a, **kw: captured["bulk_insert"].append(a)
    module.op.get_bind = lambda *a, **kw: captured["get_bind"].append(a) or None

    getattr(module, direction)()
    return captured


def _created_table():
    """Bind the captured create_table() arguments into a real Table on a fresh
    MetaData, so constraints can be inspected through public API. An unbound
    UniqueConstraint reports no columns at all, which would let a wrong-column
    assertion pass vacuously."""
    name, cols = _capture("upgrade")["create_table"][0]
    table = sa.Table(name, sa.MetaData(), *cols)
    columns = {c.name: c for c in table.columns}
    constraints = list(table.constraints)
    return name, columns, constraints


# --- revision chain ---------------------------------------------------------


def test_migration_extends_the_promotion_state_head():
    module = _load_migration()
    assert module.revision == "b8e3f1a70d95"
    assert module.down_revision == "c4a7e9d15b83"


# --- upgrade shape ----------------------------------------------------------


def test_upgrade_creates_exactly_one_table():
    captured = _capture("upgrade")
    assert len(captured["create_table"]) == 1
    assert captured["create_table"][0][0] == "source_collection_attempts"


def test_upgrade_touches_no_existing_row():
    """The point of the file: no UPDATE, no INSERT, no raw connection."""
    captured = _capture("upgrade")
    assert captured["execute"] == []
    assert captured["bulk_insert"] == []
    assert captured["get_bind"] == []


def test_the_columns_match_the_model_exactly():
    _, columns, _ = _created_table()
    assert set(columns) == {c.name for c in SourceCollectionAttempt.__table__.columns}


def test_selected_at_is_not_nullable_but_started_and_finished_are():
    """The semantic distinction this table exists for: a mapping that was
    selected and then skipped has no started_at, and that is a real state
    rather than missing data."""
    _, columns, _ = _created_table()
    assert columns["selected_at"].nullable is False
    assert columns["started_at"].nullable is True
    assert columns["finished_at"].nullable is True


def test_selection_ordinal_is_nullable():
    """A single-mapping CLI run has no position in a population; writing 0
    would be an invented fact."""
    _, columns, _ = _created_table()
    assert columns["selection_ordinal"].nullable is True


def test_failure_reason_is_length_bounded_not_free_text():
    _, columns, _ = _created_table()
    reason = columns["failure_reason"]
    assert isinstance(reason.type, sa.String)
    assert reason.type.length == 500
    assert not isinstance(reason.type, sa.Text)


def test_status_and_source_denied_are_not_nullable():
    _, columns, _ = _created_table()
    assert columns["status"].nullable is False
    assert columns["source_denied"].nullable is False


def test_price_observation_id_is_nullable():
    """Most attempts never produce an observation, and a pruned observation
    must not take its explanation with it."""
    _, columns, _ = _created_table()
    assert columns["price_observation_id"].nullable is True


# --- constraints ------------------------------------------------------------


def _constraint_names(constraints):
    return {c.name for c in constraints if getattr(c, "name", None)}


def test_status_vocabulary_is_enforced_and_includes_selected():
    _, _, constraints = _created_table()
    check = next(
        c
        for c in constraints
        if getattr(c, "name", None) == "ck_source_collection_attempts_status"
    )
    condition = str(check.sqltext)
    for status in STATUSES:
        assert f"'{status}'" in condition
    assert "'selected'" in condition


def test_failure_stage_vocabulary_is_enforced_and_allows_null():
    _, _, constraints = _created_table()
    check = next(
        c
        for c in constraints
        if getattr(c, "name", None) == "ck_source_collection_attempts_failure_stage"
    )
    condition = str(check.sqltext)
    assert "failure_stage IS NULL" in condition
    for stage in FAILURE_STAGES:
        assert f"'{stage}'" in condition


def test_finished_at_is_set_exactly_when_the_row_is_terminal():
    """A biconditional, not an implication. The weaker
    "status = 'selected' OR finished_at IS NOT NULL" caught an unfinished
    terminal row but accepted a 'selected' row carrying a finish time - a state
    the lifecycle has no meaning for."""
    _, _, constraints = _created_table()
    check = next(
        c
        for c in constraints
        if getattr(c, "name", None)
        == "ck_source_collection_attempts_finished_iff_terminal"
    )
    assert "(status = 'selected') = (finished_at IS NULL)" in str(check.sqltext)


def test_the_weaker_implication_form_is_gone():
    _, _, constraints = _created_table()
    conditions = " ".join(
        str(getattr(c, "sqltext", "")) for c in constraints
    )
    assert "status = 'selected' OR finished_at IS NOT NULL" not in conditions


def test_finishing_without_starting_is_not_forbidden():
    """The removed constraint must stay removed: a skipped mapping finishes
    without ever starting."""
    _, _, constraints = _created_table()
    names = {getattr(c, "name", None) for c in constraints}
    assert "ck_source_collection_attempts_finished_implies_started" not in names


def test_finish_may_not_precede_start_when_both_are_known():
    _, _, constraints = _created_table()
    check = next(
        c
        for c in constraints
        if getattr(c, "name", None)
        == "ck_source_collection_attempts_finished_after_started"
    )
    condition = str(check.sqltext)
    assert "finished_at IS NULL OR started_at IS NULL" in condition
    assert "finished_at >= started_at" in condition


def test_selection_ordinal_must_be_positive_when_present():
    _, _, constraints = _created_table()
    check = next(
        c
        for c in constraints
        if getattr(c, "name", None)
        == "ck_source_collection_attempts_selection_ordinal_positive"
    )
    assert "selection_ordinal IS NULL OR selection_ordinal > 0" in str(check.sqltext)


def test_one_mapping_per_position_per_run():
    """selection_ordinal exists so exact batch order survives log loss; two
    mappings claiming the same position would destroy that fact."""
    _, _, constraints = _created_table()
    unique = next(
        c
        for c in constraints
        if getattr(c, "name", None) == "uq_source_collection_attempts_batch_ordinal"
    )
    assert [c.name for c in unique.columns] == ["batch_run_id", "selection_ordinal"]


def test_one_row_per_run_per_mapping():
    _, _, constraints = _created_table()
    unique = next(
        c
        for c in constraints
        if getattr(c, "name", None) == "uq_source_collection_attempts_batch_mapping"
    )
    assert [c.name for c in unique.columns] == ["batch_run_id", "source_card_mapping_id"]


def test_only_the_observation_reference_is_a_foreign_key():
    """The delete-behaviour decision, pinned. The subjects are plain ids so
    history outlives them and telemetry can never block a delete; the
    observation - the one thing the app really does delete, via retention -
    keeps an FK that nulls itself rather than leaving a dangling pointer."""
    _, _, constraints = _created_table()
    by_column = {}
    for c in constraints:
        if isinstance(c, sa.ForeignKeyConstraint):
            by_column[list(c.columns)[0].name] = c.ondelete
    assert by_column == {"price_observation_id": "SET NULL"}


def test_the_subject_ids_are_still_sanity_checked():
    """Dropping the FKs must not mean accepting nonsense ids."""
    _, _, constraints = _created_table()
    names = {getattr(c, "name", None) for c in constraints}
    assert "ck_source_collection_attempts_source_id_positive" in names
    assert "ck_source_collection_attempts_mapping_id_positive" in names


# --- indexes ----------------------------------------------------------------


def test_indexes_cover_run_lookup_and_recent_history():
    captured = _capture("upgrade")
    names = {name for name, _, _ in captured["create_index"]}
    assert "ix_source_collection_attempts_batch_run_id" in names
    assert "ix_source_collection_attempts_mapping_recent" in names
    recent = next(
        cols
        for name, _, cols in captured["create_index"]
        if name == "ix_source_collection_attempts_mapping_recent"
    )
    assert recent[0] == "source_card_mapping_id"
    assert "selected_at" in str(recent[1])


# --- downgrade --------------------------------------------------------------


def test_downgrade_drops_the_table_and_its_indexes():
    captured = _capture("downgrade")
    assert captured["drop_table"] == ["source_collection_attempts"]
    assert len(captured["drop_index"]) == 3


def test_downgrade_touches_no_existing_row():
    captured = _capture("downgrade")
    assert captured["execute"] == []
    assert captured["bulk_insert"] == []
