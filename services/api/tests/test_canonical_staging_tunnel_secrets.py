"""4D-1B: nothing the Railway child process prints can reach an operator.

`railway connect --tunnel-only` prints a connection URL, and depending on
version and flags may print host, port, username, password and database
alongside it. `staging_db_read_check.open_tunnel` captures all of that -
`stdout=PIPE`, `stderr=STDOUT`, read line by line in-process - and parses out
only the `URL:` line. Nothing is inherited by the terminal.

These tests hold that shut from the outside. A fake Railway child emits the
worst realistic output on BOTH streams, and every path an operator can reach -
success, each refusal, a tunnel that never comes up, an exception from inside
the run - is checked for the password and the full DSN in stdout, stderr,
exception text, attestation serialisation, JSON output and captured logs.

The fake is a real subprocess, not a stub: `open_tunnel` runs unmodified
against it, so what is proved is the actual capture behaviour rather than a
mock of it.
"""

import json
import logging
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app import import_frozen_bandai_to_canonical_staging as runner
from app.services import canonical_staging_target as T
from tests._repo_root import find_repo_root

REPO_ROOT = find_repo_root()
pytestmark = pytest.mark.skipif(
    REPO_ROOT is None, reason="repo root not visible from this environment"
)

SECRET = "SUPERSECRET"
TUNNEL_URL = f"postgresql://railwayuser:{SECRET}@127.0.0.1:54321/railway"

# What a chatty `railway connect` can put on stdout and stderr. Every line
# here is a plausible shape, and all but the `URL:` line must be swallowed.
NOISY_STDOUT = f"""\
Connecting to Postgres on environment staging...
  Host:     containers-us-west-42.railway.app
  Port:     54321
  User:     railwayuser
  Password: {SECRET}
  Database: railway
PGPASSWORD={SECRET}
Connection string: {TUNNEL_URL}
URL: {TUNNEL_URL}
Tunnel established. Press Ctrl-C to close.
"""
NOISY_STDERR = f"""\
warning: using cached credentials
debug: DATABASE_URL={TUNNEL_URL}
debug: password={SECRET}
"""

SECRET_MARKERS = (
    SECRET,
    TUNNEL_URL,
    f"railwayuser:{SECRET}",
    f"PGPASSWORD={SECRET}",
    f"password={SECRET}",
)


def _assert_contained(*texts: str, label: str = "") -> None:
    blob = "\n".join(t for t in texts if t)
    for marker in SECRET_MARKERS:
        assert marker not in blob, f"{label}: {marker!r} leaked"


# --- the fake Railway CLI --------------------------------------------------


@pytest.fixture
def fake_railway(tmp_path: Path) -> Path:
    """A script that behaves like a noisy `railway connect --tunnel-only`.

    Writes the sensitive block to stdout AND stderr, then stays alive the way
    a real tunnel does, so `open_tunnel`'s poll/readline loop is exercised for
    real rather than against an already-exited process.
    """
    script = tmp_path / "fake_railway.py"
    script.write_text(
        "import sys, time\n"
        f"sys.stderr.write({NOISY_STDERR!r})\n"
        "sys.stderr.flush()\n"
        f"sys.stdout.write({NOISY_STDOUT!r})\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    return script


@pytest.fixture
def checker_with_fake_tunnel(monkeypatch, fake_railway: Path):
    """The REAL checker, with `railway` swapped for the noisy fake.

    Only the argv is replaced - `open_tunnel`'s Popen call, its pipe wiring
    and its parsing all run unmodified, which is what makes this a test of the
    capture behaviour.
    """
    checker = T.load_staging_checker()
    real_popen = subprocess.Popen
    calls: list[list[str]] = []

    def _popen(argv, *args, **kwargs):
        calls.append(list(argv))
        return real_popen(
            [sys.executable, str(fake_railway)], *args, **kwargs
        )

    monkeypatch.setattr(checker.subprocess, "Popen", _popen)
    checker._test_calls = calls
    return checker


def _passing_facts(checker, **overrides):
    facts = checker.Facts()
    facts.database = "railway"
    facts.transaction_read_only = "on"
    heads = checker.expected_revisions_from_repo(str(REPO_ROOT))
    facts.alembic_revisions = (next(iter(heads)),)
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


def _resolve(checker, capsys, caplog, *, facts=None, collect=None, emit_to=None):
    lines: list[str] = []
    with caplog.at_level(logging.DEBUG):
        target = T.verified_staging_target(
            checker=checker,
            collect=collect or (lambda url, c: facts),
            emit=(emit_to if emit_to is not None else lines).append
            if emit_to is not None
            else lines.append,
        )
    captured = capsys.readouterr()
    return target, lines, captured, caplog.text


# --- 1. successful target resolution ---------------------------------------


def test_a_successful_resolution_leaks_nothing(checker_with_fake_tunnel, capsys, caplog):
    checker = checker_with_fake_tunnel
    target, lines, captured, logs = _resolve(
        checker, capsys, caplog, facts=_passing_facts(checker)
    )
    try:
        _assert_contained(
            "\n".join(lines), captured.out, captured.err, logs, label="success"
        )
        # and the tunnel is still usable internally
        assert target.url.startswith("postgresql://")
        assert SECRET in target.url, "the URL must still carry real credentials"
        assert target.redacted == "127.0.0.1:54321/railway"
    finally:
        target.close()


def test_a_the_railway_child_is_invoked_with_explicit_targeting(
    checker_with_fake_tunnel, capsys, caplog
):
    """§5. Explicit environment + service + tunnel-only, and no relink."""
    checker = checker_with_fake_tunnel
    target, *_ = _resolve(checker, capsys, caplog, facts=_passing_facts(checker))
    try:
        argv = checker._test_calls[0]
        assert argv[:2] == ["railway", "connect"]
        assert "Postgres" in argv
        assert argv[argv.index("--environment") + 1] == "staging"
        assert "--tunnel-only" in argv
        assert "link" not in argv, "the runner must not relink the local checkout"
    finally:
        target.close()


def test_a_the_attestation_serialises_without_credentials(
    checker_with_fake_tunnel, capsys, caplog
):
    checker = checker_with_fake_tunnel
    target, *_ = _resolve(checker, capsys, caplog, facts=_passing_facts(checker))
    try:
        _assert_contained(
            json.dumps(target.attestation.describe()),
            json.dumps(target.attestation.__dict__, default=str),
            repr(target.attestation),
            label="attestation",
        )
    finally:
        target.close()


def test_a_the_target_repr_does_not_carry_the_url(
    checker_with_fake_tunnel, capsys, caplog
):
    """A dataclass repr reaches an operator through any %r or assert."""
    checker = checker_with_fake_tunnel
    target, *_ = _resolve(checker, capsys, caplog, facts=_passing_facts(checker))
    try:
        _assert_contained(repr(target), str(target), label="repr")
    finally:
        target.close()


# --- 2. fingerprint refusal ------------------------------------------------


def test_b_a_fingerprint_refusal_leaks_nothing(checker_with_fake_tunnel, capsys, caplog):
    checker = checker_with_fake_tunnel
    facts = _passing_facts(checker, row_counts={"canonical_cards": 0})

    with pytest.raises(T.StagingTargetRefused) as excinfo:
        _resolve(checker, capsys, caplog, facts=facts)

    captured = capsys.readouterr()
    _assert_contained(
        str(excinfo.value), repr(excinfo.value), captured.out, captured.err,
        caplog.text, label="fingerprint refusal",
    )


# --- 3. revision refusal ---------------------------------------------------


def test_c_a_revision_refusal_leaks_nothing(checker_with_fake_tunnel, capsys, caplog):
    checker = checker_with_fake_tunnel
    facts = _passing_facts(checker, alembic_revisions=("deadbeefcafe",))

    with pytest.raises(T.StagingTargetRefused) as excinfo:
        _resolve(checker, capsys, caplog, facts=facts)

    captured = capsys.readouterr()
    _assert_contained(
        str(excinfo.value), captured.out, captured.err, caplog.text,
        label="revision refusal",
    )
    assert "alembic revision" in str(excinfo.value)


# --- 4. tunnel startup failure ---------------------------------------------


def test_d_a_tunnel_that_never_reports_a_url_leaks_nothing(monkeypatch, tmp_path, capsys):
    """The child prints the whole credential block but never the URL line."""
    script = tmp_path / "no_url.py"
    script.write_text(
        "import sys, time\n"
        f"sys.stderr.write({NOISY_STDERR!r})\n"
        f"sys.stdout.write({NOISY_STDOUT.replace('URL: ', 'NOTURL: ')!r})\n"
        "sys.stdout.flush()\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )
    checker = T.load_staging_checker()
    monkeypatch.setattr(checker, "TUNNEL_READY_TIMEOUT_S", 2)
    real_popen = subprocess.Popen
    monkeypatch.setattr(
        checker.subprocess, "Popen",
        lambda argv, *a, **k: real_popen([sys.executable, str(script)], *a, **k),
    )

    with pytest.raises(T.StagingTargetRefused) as excinfo:
        T.verified_staging_target(checker=checker, emit=lambda _: None)

    captured = capsys.readouterr()
    _assert_contained(
        str(excinfo.value), repr(excinfo.value), captured.out, captured.err,
        label="tunnel startup failure",
    )
    assert "REFUSED" in str(excinfo.value)


def test_d_a_missing_railway_binary_leaks_nothing(monkeypatch, capsys):
    checker = T.load_staging_checker()

    def _boom(*_a, **_k):
        raise FileNotFoundError(2, "No such file or directory: 'railway'")

    monkeypatch.setattr(checker.subprocess, "Popen", _boom)

    with pytest.raises(T.StagingTargetRefused) as excinfo:
        T.verified_staging_target(checker=checker, emit=lambda _: None)

    captured = capsys.readouterr()
    _assert_contained(str(excinfo.value), captured.out, captured.err, label="no binary")


def test_d_a_driver_error_quoting_the_dsn_is_scrubbed(checker_with_fake_tunnel, capsys):
    """The one realistic way a DSN reaches an operator: a driver message."""
    checker = checker_with_fake_tunnel

    def _collect(url, _checker):
        raise RuntimeError(f'connection failed for "{url}" (PGPASSWORD={SECRET})')

    with pytest.raises(T.StagingTargetRefused) as excinfo:
        T.verified_staging_target(
            checker=checker, collect=_collect, emit=lambda _: None
        )

    captured = capsys.readouterr()
    _assert_contained(
        str(excinfo.value), repr(excinfo.value), captured.out, captured.err,
        label="driver error",
    )
    assert "REDACTED" in str(excinfo.value)


def test_d_a_chained_traceback_does_not_reintroduce_the_dsn(checker_with_fake_tunnel):
    """`raise ... from None`: the cause is dropped, not just the message."""
    import traceback as tb

    checker = checker_with_fake_tunnel

    def _collect(url, _checker):
        raise RuntimeError(f"boom {url}")

    try:
        T.verified_staging_target(checker=checker, collect=_collect, emit=lambda _: None)
    except T.StagingTargetRefused as exc:
        text = "".join(tb.format_exception(type(exc), exc, exc.__traceback__))
        _assert_contained(text, label="chained traceback")
    else:  # pragma: no cover
        pytest.fail("expected a refusal")


# --- 5. an exception raised inside the runner ------------------------------


def test_e_a_runner_exception_is_reported_scrubbed(monkeypatch, capsys):
    """The whole DB phase is wrapped; the traceback is printed, redacted."""
    from app.services.canonical_import_apply import StagingTargetAttestation

    attestation = StagingTargetAttestation(
        railway_environment="staging", railway_service="Postgres",
        database="railway", db_revision="abc123",
        checks=(("fingerprint A - required tables", True),),
    )
    target = T.VerifiedStagingTarget(
        attestation=attestation, url=TUNNEL_URL, redacted="127.0.0.1:54321/railway"
    )
    monkeypatch.setattr(T, "verified_staging_target", lambda **_kw: target)
    monkeypatch.setattr(runner, "target_authority", T)

    def _explode(url, *, read_only):
        raise RuntimeError(f'could not connect to "{url}" password={SECRET}')

    monkeypatch.setattr(runner, "_session_factory", _explode)

    assert runner.main([]) == runner.EXIT_FAILED
    captured = capsys.readouterr()
    _assert_contained(captured.out, captured.err, label="runner exception")
    assert "REDACTED" in captured.err
    assert "RuntimeError" in captured.err  # still debuggable


def test_e_the_runner_prints_a_traceback_that_is_scrubbed(monkeypatch, capsys):
    from app.services.canonical_import_apply import StagingTargetAttestation

    attestation = StagingTargetAttestation(
        railway_environment="staging", railway_service="Postgres",
        database="railway", db_revision="abc123",
        checks=(("fingerprint A - required tables", True),),
    )
    target = T.VerifiedStagingTarget(
        attestation=attestation, url=TUNNEL_URL, redacted="127.0.0.1:54321/railway"
    )
    monkeypatch.setattr(T, "verified_staging_target", lambda **_kw: target)
    monkeypatch.setattr(runner, "target_authority", T)
    monkeypatch.setattr(
        runner, "_session_factory",
        lambda url, *, read_only: (_ for _ in ()).throw(ValueError(url)),
    )

    runner.main([])
    captured = capsys.readouterr()

    _assert_contained(captured.out, captured.err, label="runner traceback")
    assert "Traceback" in captured.err


def test_e_the_tunnel_is_closed_even_when_the_runner_raises(monkeypatch, capsys):
    from app.services.canonical_import_apply import StagingTargetAttestation

    closed: list[int] = []
    attestation = StagingTargetAttestation(
        railway_environment="staging", railway_service="Postgres",
        database="railway", db_revision="abc123",
        checks=(("fingerprint A - required tables", True),),
    )
    target = T.VerifiedStagingTarget(
        attestation=attestation, url=TUNNEL_URL, redacted="127.0.0.1:54321/railway"
    )
    monkeypatch.setattr(target, "close", lambda: closed.append(1))
    monkeypatch.setattr(T, "verified_staging_target", lambda **_kw: target)
    monkeypatch.setattr(runner, "target_authority", T)
    monkeypatch.setattr(
        runner, "_session_factory",
        lambda url, *, read_only: (_ for _ in ()).throw(ValueError("x")),
    )

    runner.main([])

    assert closed == [1]


# --- 6. the subprocess wiring itself ---------------------------------------


def test_f_open_tunnel_captures_both_streams_and_inherits_neither():
    """Read from the source: PIPE for stdout, STDOUT for stderr."""
    source = (REPO_ROOT / "scripts" / "staging_db_read_check.py").read_text(
        encoding="utf-8"
    )
    body = source.split("def open_tunnel")[1].split("\ndef ")[0]

    assert "stdout=subprocess.PIPE" in body
    assert "stderr=subprocess.STDOUT" in body
    # nothing in the loop prints, logs or re-raises what the child said
    for forbidden in ("print(", "logger", "logging", "sys.stdout.write"):
        assert forbidden not in body, forbidden


def test_f_the_timeout_error_does_not_quote_the_child_output():
    source = (REPO_ROOT / "scripts" / "staging_db_read_check.py").read_text(
        encoding="utf-8"
    )
    body = source.split("def open_tunnel")[1].split("\ndef ")[0]
    raise_block = body.split("raise RuntimeError")[1]

    assert "captured" not in raise_block


def test_f_only_the_url_line_is_parsed_out(checker_with_fake_tunnel, capsys, caplog):
    """Every other sensitive line the child printed is discarded unread."""
    checker = checker_with_fake_tunnel
    target, lines, captured, logs = _resolve(
        checker, capsys, caplog, facts=_passing_facts(checker)
    )
    try:
        assert target.url == TUNNEL_URL
        for noisy in ("Password:", "Connection string:", "PGPASSWORD"):
            assert noisy not in "\n".join(lines)
            assert noisy not in captured.out
            assert noisy not in captured.err
    finally:
        target.close()


# --- 7. the scrubber itself ------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        f"postgresql://user:{SECRET}@host:5432/railway",
        f"postgres://user:{SECRET}@host/db",
        f"PGPASSWORD={SECRET}",
        f"password={SECRET}",
        f'password="{SECRET}"',
        f"pwd: {SECRET}",
        f"connect to postgresql://u:{SECRET}@h:1/d failed, PGPASSWORD={SECRET}",
    ],
)
def test_g_the_scrubber_removes_every_credential_shape(text):
    scrubbed = T.scrub_credentials(text)

    assert SECRET not in scrubbed
    assert "REDACTED" in scrubbed


def test_g_the_scrubber_keeps_the_non_secret_parts_readable():
    scrubbed = T.scrub_credentials(
        f"connection to postgresql://u:{SECRET}@127.0.0.1:54321/railway failed"
    )

    assert "127.0.0.1:54321/railway" in scrubbed
    assert "connection to" in scrubbed


def test_g_the_scrubber_leaves_ordinary_text_alone():
    text = "fingerprint E - non-empty invariants: canonical_cards=0"

    assert T.scrub_credentials(text) == text


# --- 8. no module on this path logs a URL ----------------------------------


def test_h_no_module_on_the_staging_path_passes_a_url_to_a_logger():
    api_root = Path(__file__).resolve().parents[1]
    for name in (
        api_root / "app" / "import_frozen_bandai_to_canonical_staging.py",
        api_root / "app" / "services" / "canonical_staging_target.py",
    ):
        source = name.read_text(encoding="utf-8")
        for number, line in enumerate(source.splitlines(), start=1):
            if re.search(r"\b(logger|logging)\b", line) and "url" in line.lower():
                pytest.fail(f"{name.name}:{number}: {line.strip()}")
