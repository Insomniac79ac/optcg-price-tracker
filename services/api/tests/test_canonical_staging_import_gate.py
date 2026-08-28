"""4D-1: the execution gate that lets ONE command write canonical staging.

Two properties are asserted here, and they pull in opposite directions:

    the generic CLI still cannot reach canonical staging, by any flag,
    any environment variable or any --database-url;

    the dedicated runner can, but only after the established fail-closed
    verification passes and only with an exact confirmation phrase.

Everything except the two disposable-database tests runs without a server.
The staging target authority is exercised against the REAL
scripts/staging_db_read_check.py - its rules, its revision expectations, its
redaction - with only `open_tunnel` and the connection substituted, so a test
passing here is evidence about the actual checker rather than about a mock of
it.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app import import_frozen_bandai_to_canonical_staging as runner
from app.services import canonical_import_apply as A
from app.services import canonical_staging_target as T
from app.services import print_import_planner as P
from tests._repo_root import find_repo_root

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = find_repo_root()

pytestmark = pytest.mark.skipif(
    REPO_ROOT is None,
    reason="repo root not visible (the api image only copies services/api) - run "
    "against a full dev checkout",
)

CONFIRM = "IMPORT_FROZEN_BANDAI_TO_CANONICAL_STAGING"

# A URL shaped like the one `railway connect --tunnel-only` hands back,
# password included, so the secret-safety tests have a real secret to look for.
TUNNEL_URL = "postgresql://postgres:sup3rs3cr3tpw@127.0.0.1:54321/railway"
TUNNEL_PASSWORD = "sup3rs3cr3tpw"


# --- the real checker, with only the tunnel substituted --------------------


class _FakeProc:
    """Stands in for the tunnel child, faithful to what `close_tunnel` uses.

    4D-1C added a drain thread and a `close_tunnel` that terminates, waits and
    closes the pipe, so a stub with only `terminate()` no longer resembles the
    thing it replaces. `stdout = None` is the honest value here: this fake was
    never handed a pipe, so there is nothing to drain or close.
    """

    def __init__(self) -> None:
        self.terminated = 0
        self.waited = 0
        self.stdout = None
        self._returncode = None

    def terminate(self) -> None:
        self.terminated += 1
        self._returncode = -15

    def kill(self) -> None:  # pragma: no cover - terminate always suffices here
        self.terminate()

    def wait(self, timeout: float | None = None) -> int:
        self.waited += 1
        if self._returncode is None:
            self._returncode = -15
        return self._returncode

    def poll(self) -> int | None:
        return self._returncode


def _checker():
    """The REAL scripts/staging_db_read_check.py module."""
    return T.load_staging_checker()


def _expected_head() -> str:
    heads = _checker().expected_revisions_from_repo(str(REPO_ROOT))
    assert len(heads) == 1, f"repo has {len(heads)} alembic heads: {sorted(heads)}"
    return next(iter(heads))


def _passing_facts(checker, **overrides):
    """Facts that satisfy every fingerprint the real checker applies."""
    facts = checker.Facts()
    facts.database = "railway"
    facts.transaction_read_only = "on"
    facts.alembic_revisions = (_expected_head(),)
    facts.tables_present = frozenset(checker.REQUIRED_TABLES)
    # Plus one name from each renamed-relation group - a real database
    # carries exactly one of them (see checker.REQUIRED_RELATION_ALTERNATIVES,
    # which spans the c9f31e2a7d04 rename of the mapping lineage key).
    facts.relations_present = frozenset(checker.REQUIRED_RELATIONS) | {
        group[-1] for group in checker.REQUIRED_RELATION_ALTERNATIVES
    }
    facts.constraints_present = frozenset(checker.REQUIRED_CONSTRAINTS)
    facts.columns_present = frozenset(checker.REQUIRED_COLUMNS)
    facts.row_counts = {t: 4260 for t in checker.NON_EMPTY_TABLES}
    for key, value in overrides.items():
        setattr(facts, key, value)
    return facts


def _target(monkeypatch, *, facts_overrides=None, environment="staging", emit=None):
    """Runs the real verification with a stubbed tunnel and connection."""
    checker = _checker()
    opened: list[tuple[str, str]] = []
    procs: list[_FakeProc] = []

    def _open_tunnel(service, env):
        opened.append((service, env))
        proc = _FakeProc()
        procs.append(proc)
        return proc, TUNNEL_URL

    monkeypatch.setattr(checker, "open_tunnel", _open_tunnel)
    facts = _passing_facts(checker, **(facts_overrides or {}))
    lines: list[str] = []

    result = T.verified_staging_target(
        environment=environment,
        checker=checker,
        collect=lambda url, _checker: facts,
        emit=(emit or lines.append),
    )
    return result, opened, procs, lines


# --- A. the generic importer still refuses staging -------------------------


def _generic_cli(*args: str, env: dict | None = None):
    return subprocess.run(
        [sys.executable, "-m", "app.apply_canonical_print_import", *args],
        cwd=API_ROOT, capture_output=True, text=True, timeout=180, env=env,
    )


def test_a_the_generic_cli_still_refuses_environment_staging():
    result = _generic_cli(
        "--database-url", "postgresql+psycopg://x/y", "--environment", "staging", "--apply"
    )

    assert result.returncode == 2
    assert "REFUSED" in result.stderr
    assert "staging" in result.stderr


def test_a_staging_is_still_in_the_generic_refusal_list():
    """The constant the generic CLI reads is unchanged by 4D-1."""
    assert "staging" in A.REFUSED_APPLY_ENVIRONMENTS
    assert "staging" not in A.ALLOWED_APPLY_ENVIRONMENTS


@pytest.mark.parametrize(
    "variable",
    [
        "ATLAS_ALLOW_STAGING_WRITE",
        "CANONICAL_STAGING_WRITE",
        "IMPORT_FROZEN_BANDAI_TO_CANONICAL_STAGING",
        "ALLOW_STAGING_APPLY",
    ],
)
def test_a_no_environment_variable_unlocks_staging_on_the_generic_cli(variable):
    """§6. Permission is an object; nothing in the environment can be it."""
    import os

    env = dict(os.environ)
    env[variable] = "1"
    env["ATLAS_STAGING_WRITE_CONFIRMATION"] = CONFIRM
    result = _generic_cli(
        "--database-url", "postgresql+psycopg://x/y", "--environment", "staging",
        "--apply", env=env,
    )

    assert result.returncode == 2
    assert "REFUSED" in result.stderr


def test_a_the_generic_cli_exposes_no_flag_that_could_carry_a_grant():
    parser = __import__(
        "app.apply_canonical_print_import", fromlist=["build_parser"]
    ).build_parser()
    flags = {opt for action in parser._actions for opt in action.option_strings}

    assert not flags & {"--grant", "--confirm", "--yes", "--force", "--allow-staging"}


def test_a_the_engine_refuses_staging_without_a_grant():
    with pytest.raises(A.ApplyAborted) as excinfo:
        _applier(environment="staging", staging_grant=None)._check_environment()

    assert excinfo.value.reason == "refused_environment"


# --- B. production and prod are permanently refused ------------------------


@pytest.mark.parametrize("environment", ["production", "prod", "PRODUCTION", "Prod"])
def test_b_the_generic_cli_still_hard_refuses_production(environment):
    result = _generic_cli(
        "--database-url", "postgresql+psycopg://x/y", "--environment", environment, "--apply"
    )

    assert result.returncode == 2
    assert "REFUSED" in result.stderr


@pytest.mark.parametrize("environment", ["production", "prod"])
def test_b_a_valid_grant_cannot_unlock_production(environment):
    """The permanent refusal returns before any authorisation is consulted."""
    grant = A.grant_canonical_staging_write(
        confirmation=CONFIRM, attestation=_attestation()
    )

    with pytest.raises(A.ApplyAborted) as excinfo:
        _applier(environment=environment, staging_grant=grant)._check_environment()

    assert excinfo.value.reason == "refused_environment"
    assert environment in excinfo.value.detail


def test_b_production_is_in_the_permanent_list_and_staging_is_not():
    assert A.PERMANENTLY_REFUSED_APPLY_ENVIRONMENTS == ("production", "prod")
    assert "staging" not in A.PERMANENTLY_REFUSED_APPLY_ENVIRONMENTS


def test_b_the_production_refusal_is_read_before_the_grant_branch():
    """Ordering, read from the source rather than inferred."""
    source = (
        API_ROOT / "app" / "services" / "canonical_import_apply.py"
    ).read_text(encoding="utf-8")
    body = source.split("def _check_environment")[1].split("\n    def ")[0]

    assert body.index("PERMANENTLY_REFUSED_APPLY_ENVIRONMENTS") < body.index(
        "_staging_grant"
    )


# --- C. the dedicated runner takes no database URL -------------------------


def test_c_the_runner_has_no_database_url_flag():
    flags = {
        opt for action in runner.build_parser()._actions for opt in action.option_strings
    }

    assert "--database-url" not in flags
    assert not flags & {"--url", "--dsn", "--url-env", "--force", "--yes"}


def test_c_passing_a_database_url_is_an_argparse_error():
    with pytest.raises(SystemExit) as excinfo:
        runner.main(["--database-url", "postgresql://attacker/evil", "--apply",
                     "--confirm", CONFIRM])

    assert excinfo.value.code == 2


def test_c_the_runner_never_reads_a_url_from_the_environment(monkeypatch):
    """The connection comes from Railway, not from a variable a caller sets."""
    source = (
        API_ROOT / "app" / "import_frozen_bandai_to_canonical_staging.py"
    ).read_text(encoding="utf-8")

    assert "DATABASE_URL" not in source
    assert "os.environ" not in source
    assert "getenv" not in source


def test_c_the_target_authority_takes_no_caller_supplied_url():
    import inspect

    parameters = inspect.signature(T.verified_staging_target).parameters

    assert "url" not in parameters
    assert "database_url" not in parameters


# --- D. a wrong Railway environment refuses --------------------------------


@pytest.mark.parametrize("environment", ["production", "prod", "dev", "staging2", ""])
def test_d_the_runner_refuses_any_environment_but_staging(environment, capsys):
    assert runner.main(["--railway-environment", environment]) == 2
    assert "REFUSED" in capsys.readouterr().err


@pytest.mark.parametrize("environment", ["production", "prod", "dev", "review"])
def test_d_the_target_authority_refuses_before_opening_a_tunnel(monkeypatch, environment):
    checker = _checker()
    opened = []
    monkeypatch.setattr(
        checker, "open_tunnel", lambda s, e: opened.append((s, e)) or (None, "")
    )

    with pytest.raises(T.StagingTargetRefused):
        T.verified_staging_target(environment=environment, checker=checker, emit=lambda _: None)

    assert opened == [], "a tunnel was opened into a refused environment"


def test_d_the_accepted_environment_reaches_railway_verbatim(monkeypatch):
    _result, opened, _procs, _lines = _target(monkeypatch)

    assert [env for _service, env in opened] == ["staging", "staging"]


# --- E. a failed staging fingerprint refuses -------------------------------


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"row_counts": {"canonical_cards": 0, "card_prints": 9, "sources": 3}},
         "non-empty"),
        ({"tables_present": frozenset(("alembic_version",))}, "required tables"),
        ({"relations_present": frozenset()}, "indexes/constraints"),
        ({"columns_present": frozenset()}, "print-lineage"),
        ({"transaction_read_only": "off"}, "read-only"),
    ],
)
def test_e_a_failed_fingerprint_refuses(monkeypatch, overrides, expected):
    with pytest.raises(T.StagingTargetRefused) as excinfo:
        _target(monkeypatch, facts_overrides=overrides)

    assert "REFUSED" in str(excinfo.value)
    assert expected in str(excinfo.value)


def test_e_an_empty_database_that_answers_is_refused(monkeypatch):
    """The 2026-08-21 failure mode: reachable, named 'railway', and empty."""
    with pytest.raises(T.StagingTargetRefused):
        _target(
            monkeypatch,
            facts_overrides={
                "tables_present": frozenset(),
                "relations_present": frozenset(),
                "constraints_present": frozenset(),
                "columns_present": frozenset(),
                "alembic_revisions": (),
                "row_counts": {},
            },
        )


def test_e_a_failed_fingerprint_closes_the_tunnel(monkeypatch):
    checker = _checker()
    procs = []

    def _open_tunnel(service, env):
        proc = _FakeProc()
        procs.append(proc)
        return proc, TUNNEL_URL

    monkeypatch.setattr(checker, "open_tunnel", _open_tunnel)
    facts = _passing_facts(checker, row_counts={"canonical_cards": 0})

    with pytest.raises(T.StagingTargetRefused):
        T.verified_staging_target(
            checker=checker, collect=lambda u, c: facts, emit=lambda _: None
        )

    assert len(procs) == 1 and procs[0].terminated == 1


def test_e_the_engine_refuses_a_grant_whose_checks_did_not_pass():
    attestation = _attestation(checks=(("fingerprint E - non-empty invariants", False),))

    with pytest.raises(A.ApplyAborted) as excinfo:
        A.grant_canonical_staging_write(confirmation=CONFIRM, attestation=attestation)

    assert excinfo.value.reason == "staging_target_not_attested"


def test_e_an_attestation_with_no_checks_at_all_is_refused():
    with pytest.raises(A.ApplyAborted):
        A.grant_canonical_staging_write(
            confirmation=CONFIRM, attestation=_attestation(checks=())
        )


# --- F. a wrong alembic revision refuses -----------------------------------


def test_f_a_revision_that_is_not_the_repo_head_refuses(monkeypatch):
    """The established checker's own fingerprint D catches it first."""
    with pytest.raises(T.StagingTargetRefused) as excinfo:
        _target(monkeypatch, facts_overrides={"alembic_revisions": ("deadbeefcafe",)})

    assert "REFUSED" in str(excinfo.value)
    assert "alembic revision" in str(excinfo.value)


def test_f_multiple_revisions_refuse(monkeypatch):
    """A partially-migrated database reports more than one head."""
    with pytest.raises(T.StagingTargetRefused) as excinfo:
        _target(
            monkeypatch,
            facts_overrides={"alembic_revisions": (_expected_head(), "deadbeefcafe")},
        )

    assert "REFUSED" in str(excinfo.value)


def test_f_a_database_with_no_revision_at_all_refuses(monkeypatch):
    with pytest.raises(T.StagingTargetRefused):
        _target(monkeypatch, facts_overrides={"alembic_revisions": ()})


def test_f_the_runner_pins_the_engine_to_the_attested_revision():
    """§5. The attested revision is what ApplyPinning is built from."""
    source = (
        API_ROOT / "app" / "import_frozen_bandai_to_canonical_staging.py"
    ).read_text(encoding="utf-8")

    assert "expected_db_revision=attestation.db_revision" in source


def test_f_the_attested_revision_is_the_repo_head(monkeypatch):
    result, _opened, _procs, _lines = _target(monkeypatch)

    assert result.attestation.db_revision == _expected_head()


def test_f_a_grant_bound_to_another_revision_is_refused_at_write_time():
    """§5. The grant is re-proved against the session that will write."""
    grant = A.grant_canonical_staging_write(
        confirmation=CONFIRM, attestation=_attestation(db_revision="aaaa1111bbbb")
    )
    applier = _applier(
        environment="staging", staging_grant=grant, revision="cccc2222dddd"
    )

    with pytest.raises(A.ApplyAborted) as excinfo:
        applier._check_staging_grant()

    assert excinfo.value.reason == "staging_target_revision_mismatch"


def test_f_an_attestation_with_no_revision_cannot_be_granted():
    with pytest.raises(A.ApplyAborted):
        A.grant_canonical_staging_write(
            confirmation=CONFIRM, attestation=_attestation(db_revision="")
        )


# --- G. the confirmation phrase -------------------------------------------


@pytest.mark.parametrize(
    "confirmation",
    [
        None,
        "",
        "yes",
        "import_frozen_bandai_to_canonical_staging",
        "IMPORT_FROZEN_BANDAI_TO_CANONICAL_STAGIN",
        "IMPORT_FROZEN_BANDAI_TO_CANONICAL_STAGING ",
        " IMPORT_FROZEN_BANDAI_TO_CANONICAL_STAGING",
        "IMPORT-FROZEN-BANDAI-TO-CANONICAL-STAGING",
        "IMPORT_FROZEN_BANDAI_TO_CANONICAL_PRODUCTION",
    ],
)
def test_g_a_missing_or_mistyped_confirmation_refuses_apply(confirmation, capsys, monkeypatch):
    """Refused before a tunnel is opened, so a typo never touches staging."""
    monkeypatch.setattr(
        T, "verified_staging_target",
        lambda **_kw: pytest.fail("a tunnel was opened despite a bad confirmation"),
    )
    argv = ["--apply"] + ([] if confirmation is None else ["--confirm", confirmation])

    assert runner.main(argv) == 2
    assert "REFUSED" in capsys.readouterr().err


@pytest.mark.parametrize(
    "confirmation", ["", "yes", "import_frozen_bandai_to_canonical_staging"]
)
def test_g_the_grant_factory_refuses_a_mistyped_confirmation(confirmation):
    with pytest.raises(A.ApplyAborted) as excinfo:
        A.grant_canonical_staging_write(
            confirmation=confirmation, attestation=_attestation()
        )

    assert excinfo.value.reason == "staging_confirmation_mismatch"


def test_g_the_runner_offers_no_force_or_yes_shortcut():
    flags = {
        opt for action in runner.build_parser()._actions for opt in action.option_strings
    }

    assert not flags & {"--force", "--yes", "-y", "--no-confirm", "--i-know-what-im-doing"}


def test_g_confirm_without_apply_is_refused(capsys):
    assert runner.main(["--confirm", CONFIRM]) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_g_a_grant_cannot_be_constructed_without_the_module_key():
    """§6. Importing the class is not the same as obtaining permission."""
    with pytest.raises(PermissionError):
        A.CanonicalStagingWriteGrant("not-the-key", _attestation())

    with pytest.raises(PermissionError):
        A.CanonicalStagingWriteGrant(object(), _attestation())


def test_g_a_forged_object_is_rejected_by_the_engine():
    class _Forged:
        attestation = _attestation()

    applier = _applier(environment="staging", staging_grant=_Forged())

    with pytest.raises(A.ApplyAborted) as excinfo:
        applier._check_staging_grant()

    assert excinfo.value.reason == "staging_target_not_attested"


def test_g_a_grant_authorises_staging_and_nothing_else():
    grant = A.grant_canonical_staging_write(
        confirmation=CONFIRM, attestation=_attestation()
    )

    with pytest.raises(A.ApplyAborted) as excinfo:
        _applier(environment="test", staging_grant=grant)._check_environment()

    assert excinfo.value.reason == "refused_environment"


# --- H. the dry run is read-only ------------------------------------------


def _has_connect_listener(engine) -> bool:
    # SQLAlchemy registers connect listeners of its own, so presence is read by
    # NAME rather than by count. The `connect` event lives on the pool's
    # dispatch, not the engine's, and an empty dispatch raises AttributeError.
    try:
        return any(fn.__name__ == "_set_read_only" for fn in engine.pool.dispatch.connect)
    except AttributeError:
        return False


def test_h_a_dry_run_session_registers_the_read_only_hook():
    engine = runner._session_factory(TUNNEL_URL, read_only=True)
    try:
        assert engine.dialect.name == "postgresql"
        assert _has_connect_listener(engine)
    finally:
        engine.dispose()


def test_h_an_apply_session_registers_no_read_only_hook():
    engine = runner._session_factory(TUNNEL_URL, read_only=False)
    try:
        assert not _has_connect_listener(engine)
    finally:
        engine.dispose()


def test_h_the_server_itself_rejects_a_write_on_a_dry_run_session():
    """Not "the code does not write" - the database refuses to let it."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, OperationalError

    url = _disposable_postgres_url()
    engine = runner._session_factory(url, read_only=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
            with pytest.raises((DBAPIError, OperationalError)) as excinfo:
                connection.execute(text("CREATE TABLE dry_run_should_never_write (x int)"))
        assert "read-only" in str(excinfo.value).lower()
    finally:
        engine.dispose()


def test_h_the_same_session_factory_writes_when_applying():
    """The read-only hook is the only difference, so H proves something."""
    from sqlalchemy import text

    url = _disposable_postgres_url()
    engine = runner._session_factory(url, read_only=False)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE apply_may_write (x int)"))
            connection.execute(text("DROP TABLE apply_may_write"))
    finally:
        engine.dispose()


def test_h_the_runner_asks_for_read_only_exactly_when_not_applying():
    source = (
        API_ROOT / "app" / "import_frozen_bandai_to_canonical_staging.py"
    ).read_text(encoding="utf-8")

    assert "_session_factory(verified.url, read_only=not args.apply)" in source


def test_h_a_dry_run_needs_no_confirmation_and_mints_no_grant():
    source = (
        API_ROOT / "app" / "import_frozen_bandai_to_canonical_staging.py"
    ).read_text(encoding="utf-8")
    body = source.split("grant = (")[1].split(")\n            applier")[0]

    assert "if args.apply" in body
    assert "else None" in body


# --- K. no secrets in normal or refusal output -----------------------------

SECRET_PATTERNS = (TUNNEL_PASSWORD, "postgres:", "@127.0.0.1", "postgresql://")


def test_k_verification_output_names_the_target_without_the_url(monkeypatch):
    result, _opened, _procs, lines = _target(monkeypatch)
    output = "\n".join(lines)

    for secret in SECRET_PATTERNS:
        assert secret not in output, f"{secret!r} leaked into verification output"
    assert "127.0.0.1:54321/railway" in output  # host:port/db, already non-secret
    assert "staging" in output
    assert result.redacted == "127.0.0.1:54321/railway"


def test_k_the_attestation_carries_no_credential(monkeypatch):
    result, _opened, _procs, _lines = _target(monkeypatch)
    described = json.dumps(result.attestation.describe())

    for secret in SECRET_PATTERNS:
        assert secret not in described
    assert not hasattr(result.attestation, "url")


def test_k_a_refusal_never_echoes_the_confirmation_phrase():
    with pytest.raises(A.ApplyAborted) as excinfo:
        A.grant_canonical_staging_write(
            confirmation="hunter2-almost-right", attestation=_attestation()
        )

    assert "hunter2" not in str(excinfo.value)


def test_k_a_refused_target_names_no_url(monkeypatch):
    with pytest.raises(T.StagingTargetRefused) as excinfo:
        _target(monkeypatch, facts_overrides={"alembic_revisions": ("deadbeefcafe",)})

    message = str(excinfo.value)
    for secret in SECRET_PATTERNS:
        assert secret not in message


@pytest.mark.parametrize(
    "argv",
    [
        ["--railway-environment", "production"],
        ["--apply"],
        ["--apply", "--confirm", "wrong"],
        ["--confirm", CONFIRM],
    ],
)
def test_k_runner_refusals_emit_no_secrets(argv, capsys):
    runner.main(argv)
    captured = capsys.readouterr()
    output = captured.out + captured.err

    for secret in (TUNNEL_PASSWORD, "postgresql://", "RAILWAY_TOKEN"):
        assert secret not in output


def test_k_neither_new_module_logs_a_url():
    for name in (
        API_ROOT / "app" / "import_frozen_bandai_to_canonical_staging.py",
        API_ROOT / "app" / "services" / "canonical_staging_target.py",
    ):
        source = name.read_text(encoding="utf-8")
        for line in source.splitlines():
            statement = line.strip()
            if not (statement.startswith("emit(") or statement.startswith("print(")):
                continue
            assert not re.search(r"\{\s*url\b", statement), f"{name.name}: {statement}"
            assert "verified.url" not in statement, f"{name.name}: {statement}"


# --- J. the wrapper adds no bypass of its own ------------------------------


def _code_only(path: Path) -> str:
    """Source with comments and string literals removed.

    Prose is not the thing under test - a date in a docstring is not a
    hardcoded catalogue count, and asserting over raw text would say it was.
    """
    import io
    import tokenize

    kept = []
    with path.open("rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(token.string)
    return " ".join(kept)


NEW_MODULES = (
    API_ROOT / "app" / "import_frozen_bandai_to_canonical_staging.py",
    API_ROOT / "app" / "services" / "canonical_staging_target.py",
)


@pytest.mark.parametrize("module", NEW_MODULES, ids=lambda p: p.name)
def test_j_the_wrapper_hardcodes_no_catalogue_count(module):
    """§5. Expected counts are the engine's preflight to check, not this
    wrapper's to assert - so no count is baked in to be compared against."""
    assert not re.search(r"(?<![\w.])\d{4,}(?![\w.])", _code_only(module))


@pytest.mark.parametrize("module", NEW_MODULES, ids=lambda p: p.name)
def test_j_the_wrapper_reimplements_no_planner_or_apply_logic(module):
    """§3. It resolves a target and calls the engine; it composes nothing."""
    code = _code_only(module)

    for forbidden in ("INSERT", "UPDATE ", "DELETE", "session.add", "session.commit"):
        assert forbidden not in code, forbidden


def test_j_the_runner_calls_the_existing_planner_and_applier():
    source = (
        API_ROOT / "app" / "import_frozen_bandai_to_canonical_staging.py"
    ).read_text(encoding="utf-8")

    assert "plan_entries(" in source
    assert "CanonicalImportApplier(" in source
    assert "applier.run(apply=args.apply)" in source


def test_j_the_runner_passes_every_pinning_the_engine_checks():
    """A wrapper that dropped a pin would silently weaken the engine."""
    source = (
        API_ROOT / "app" / "import_frozen_bandai_to_canonical_staging.py"
    ).read_text(encoding="utf-8")

    for pin in (
        "snapshot_identity=snapshot.identity",
        "expected_db_revision=attestation.db_revision",
        "expected_pre_counts=expected_counts",
        "expected_snapshot_identity=args.expect_snapshot",
    ):
        assert pin in source, pin


def test_j_the_runner_never_fetches_from_bandai():
    """Input is the frozen snapshot. There is no flag that makes it fetch."""
    code = _code_only(
        API_ROOT / "app" / "import_frozen_bandai_to_canonical_staging.py"
    )

    for forbidden in ("urllib", "requests", "httpx", "urlopen"):
        assert forbidden not in code, forbidden


# --- shared fixtures -------------------------------------------------------


def _disposable_postgres_url() -> str:
    """The local throwaway Postgres, or a skip. Never canonical staging."""
    import os

    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError

    host = os.environ.get("TEST_POSTGRES_HOST", "localhost")
    port = os.environ.get("TEST_POSTGRES_PORT", "5544")
    user = os.environ.get("TEST_POSTGRES_USER", "opcg")
    password = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
    url = f"postgresql+psycopg://{user}:{password}@{host}:{port}/postgres"
    try:
        engine = create_engine(url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
    except OperationalError:
        pytest.skip(f"No PostgreSQL server reachable at {host}:{port}")
    return url


def _attestation(**overrides) -> A.StagingTargetAttestation:
    values = dict(
        railway_environment="staging",
        railway_service="Postgres",
        database="railway",
        db_revision="aaaa1111bbbb",
        checks=(
            ("session is read-only", True),
            ("fingerprint A - required tables", True),
            ("fingerprint B - named indexes/constraints", True),
            ("fingerprint C - print-lineage columns", True),
            ("fingerprint D - alembic revision", True),
            ("fingerprint E - non-empty invariants", True),
        ),
    )
    values.update(overrides)
    return A.StagingTargetAttestation(**values)


class _RevisionSession:
    """Just enough session for the guards that only read the revision."""

    def __init__(self, revision: str | None) -> None:
        self._revision = revision
        self.bind = None

    def execute(self, *_args, **_kwargs):
        session = self

        class _Result:
            def first(self):
                return (session._revision,) if session._revision else None

        return _Result()


def _applier(*, environment, staging_grant, revision="aaaa1111bbbb"):
    return A.CanonicalImportApplier(
        _RevisionSession(revision),
        P.ImportPlan(prints=[]),
        pinning=A.ApplyPinning(snapshot_identity="s" * 64),
        environment=environment,
        staging_grant=staging_grant,
    )
