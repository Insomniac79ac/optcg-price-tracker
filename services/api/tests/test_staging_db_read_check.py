"""Tests for scripts/staging_db_read_check.py - the fail-closed validator that
proves a connection really is the Atlas staging database before any audit
trusts its query results.

The rules live in a pure function (`evaluate`), so the interesting cases - an
empty database, a partially-migrated one, one with the right table names but
the wrong provenance - are exercised here without needing a live Postgres. The
live path is covered separately by running the script itself against staging.

Mirrors tests/test_release_candidate_audit_script.py for the repo-root-script
skip convention (scripts/ is not copied into the api Docker image).
"""

import importlib.util
import sys

import pytest

from tests._repo_root import find_repo_root

REPO_ROOT = find_repo_root()
pytestmark = pytest.mark.skipif(
    REPO_ROOT is None,
    reason="repo root not visible from this environment (e.g. the api Docker image only "
    "copies services/api to /app) - run against a full dev checkout to exercise these",
)
SCRIPT_PATH = REPO_ROOT / "scripts" / "staging_db_read_check.py" if REPO_ROOT else None


def _load_module():
    """Imports the script by path and registers it in sys.modules.

    The registration is required, not incidental: @dataclass resolves its
    annotations through sys.modules[cls.__module__], and raises AttributeError
    if the module was never registered there.
    """
    spec = importlib.util.spec_from_file_location("staging_db_read_check", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["staging_db_read_check"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


@pytest.fixture
def good_facts(mod):
    """Facts as collected from a healthy Atlas staging database."""
    return mod.Facts(
        database="railway",
        transaction_read_only="on",
        alembic_revisions=("a9c4e17b6d52",),
        tables_present=frozenset(mod.REQUIRED_TABLES),
        relations_present=frozenset(mod.REQUIRED_RELATIONS),
        constraints_present=frozenset(mod.REQUIRED_CONSTRAINTS),
        columns_present=frozenset(mod.REQUIRED_COLUMNS),
        row_counts={t: 1 for t in mod.NON_EMPTY_TABLES},
    )


EXPECTED = frozenset({"a9c4e17b6d52"})


def _failed(results):
    return [r.name for r in results if not r.ok]


# --- the script exists and is runnable -------------------------------------


def test_script_exists():
    assert SCRIPT_PATH.is_file()


def test_script_never_writes(mod):
    """No write verb anywhere in the file - this is a validator, not a tool that
    can be talked into mutating."""
    contents = SCRIPT_PATH.read_text().lower()
    for verb in ("insert into", "update ", "delete from", "drop table", "alter table"):
        # `create table` appears only inside a test-facing docstring, so the
        # check is on genuine SQL-issuing verbs.
        assert verb not in contents.replace("cannot execute create table", ""), verb


# --- the happy path ---------------------------------------------------------


def test_healthy_staging_passes_every_fingerprint(mod, good_facts):
    results = mod.evaluate(good_facts, EXPECTED)
    assert _failed(results) == []
    assert len(results) == 6


# --- the incident: a wrong database that answers instead of erroring --------


def test_empty_database_fails_closed(mod):
    """The 2026-08-21 incident shape: a live Postgres, authenticating fine,
    current_database()='railway', but no Atlas schema. Must fail."""
    empty = mod.Facts(
        database="railway",
        transaction_read_only="on",
        row_counts={t: 0 for t in mod.NON_EMPTY_TABLES},
    )
    results = mod.evaluate(empty, EXPECTED)
    assert len(_failed(results)) == 5, "every schema fingerprint should fail on an empty DB"


def test_zero_rows_is_never_proof_of_validity(mod, good_facts):
    """Emptiness must be a failure, not a pass - the whole point of the rule."""
    facts = mod.Facts(**{**good_facts.__dict__, "row_counts": {t: 0 for t in mod.NON_EMPTY_TABLES}})
    results = mod.evaluate(facts, EXPECTED)
    assert "fingerprint E - non-empty invariants" in _failed(results)


def test_collection_items_emptiness_does_not_fail_the_check(mod, good_facts):
    """collection_items is legitimately 0 on staging. Asserting it non-empty
    would fail against the *real* database - the inversion of the bug."""
    assert "collection_items" not in mod.NON_EMPTY_TABLES
    facts = mod.Facts(**{**good_facts.__dict__, "row_counts": {**good_facts.row_counts, "collection_items": 0}})
    assert _failed(mod.evaluate(facts, EXPECTED)) == []


# --- each fingerprint is independently load-bearing ------------------------


def test_missing_table_fails(mod, good_facts):
    facts = mod.Facts(**{**good_facts.__dict__,
                         "tables_present": frozenset(mod.REQUIRED_TABLES) - {"card_prints"}})
    assert "fingerprint A - required tables" in _failed(mod.evaluate(facts, EXPECTED))


def test_right_tables_but_wrong_provenance_fails(mod, good_facts):
    """A scaffold or another project's database could share table names. The
    named-constraint fingerprint is what catches it."""
    facts = mod.Facts(**{**good_facts.__dict__,
                         "relations_present": frozenset(),
                         "constraints_present": frozenset()})
    failed = _failed(mod.evaluate(facts, EXPECTED))
    assert "fingerprint B - named indexes/constraints" in failed
    assert "fingerprint A - required tables" not in failed


def test_missing_print_lineage_column_fails(mod, good_facts):
    facts = mod.Facts(**{**good_facts.__dict__,
                         "columns_present": frozenset(mod.REQUIRED_COLUMNS)
                         - {("price_observations", "card_print_id")}})
    assert "fingerprint C - print-lineage columns" in _failed(mod.evaluate(facts, EXPECTED))


def test_partially_migrated_database_fails(mod, good_facts):
    """Right schema shape, older revision - e.g. a restored backup. Must fail
    on D even though everything else looks right."""
    facts = mod.Facts(**{**good_facts.__dict__, "alembic_revisions": ("b858237e3706",)})
    failed = _failed(mod.evaluate(facts, EXPECTED))
    assert failed == ["fingerprint D - alembic revision"]


def test_missing_alembic_revision_fails(mod, good_facts):
    facts = mod.Facts(**{**good_facts.__dict__, "alembic_revisions": ()})
    assert "fingerprint D - alembic revision" in _failed(mod.evaluate(facts, EXPECTED))


def test_read_write_session_fails(mod, good_facts):
    facts = mod.Facts(**{**good_facts.__dict__, "transaction_read_only": "off"})
    assert "session is read-only" in _failed(mod.evaluate(facts, EXPECTED))


# --- environment refusals ---------------------------------------------------


@pytest.mark.parametrize("environment", ["production", "prod", "PRODUCTION"])
def test_refuses_production(mod, environment):
    assert mod.main(["--environment", environment]) == 2


def test_refuses_unexpected_environment(mod):
    assert mod.main(["--environment", "somewhere-else"]) == 2


def test_missing_url_env_var_is_an_error_not_a_pass(mod, monkeypatch):
    monkeypatch.delenv("ATLAS_CHECK_URL_UNSET", raising=False)
    assert mod.main(["--url-env", "ATLAS_CHECK_URL_UNSET"]) == 2


# --- expectations follow the repo, not a hardcoded constant ----------------


def test_expected_revision_is_read_from_the_migration_scripts(mod):
    """The expected revision must track the checkout's alembic head, so the
    check does not silently drift behind the repo."""
    revisions = mod.expected_revisions_from_repo(str(REPO_ROOT))
    assert revisions, "should discover at least one head revision"
    versions = (REPO_ROOT / "services" / "api" / "alembic" / "versions").glob("*.py")
    assert len(list(versions)) > len(revisions), "heads should be fewer than all migrations"


# --- secrets never reach the output ----------------------------------------


def test_redacted_target_omits_credentials(mod):
    target = mod.redacted_target("postgresql://someuser:sup3rsecret@db.example.com:5432/railway")
    assert target == "db.example.com:5432/railway"
    assert "sup3rsecret" not in target
    assert "someuser" not in target
