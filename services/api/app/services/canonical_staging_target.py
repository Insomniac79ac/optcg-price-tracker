"""The single authority for "this connection is canonical Atlas staging".

WHY THIS MODULE EXISTS. Three callers now need to prove a connection is the
one canonical Railway staging Postgres before they use it - the planner CLI,
the snapshot collector, and (4D-1) the dedicated staging import runner, which
is the only path in the repo that may WRITE there. Three copies of that proof
would eventually become three different proofs, and the weakest would win.

So the proof is not restated here. `scripts/staging_db_read_check.py` is the
established fail-closed validator - written after the 2026-08-21 incident in
which a stale `DATABASE_PUBLIC_URL` connected successfully to an EMPTY
database that answered to the same name - and this module loads that script
and calls ITS tunnel opener, ITS fact collection and ITS rules. What is added
here is only packaging: the result comes back as a
`StagingTargetAttestation` the apply engine can be handed, instead of a bare
URL the caller has to be trusted to have checked.

WHAT THE CALLER GETS, AND DOES NOT GET. `verified_staging_target()` returns
the attestation plus a live tunnel URL. The URL is a credential: it is never
logged, never put in the attestation, and never returned to a caller that did
not pass verification. There is no parameter that supplies a URL from
outside - the connection is resolved from the Railway `staging` environment
itself, through `railway connect --tunnel-only`, exactly as the checker does.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.services.canonical_import_apply import StagingTargetAttestation

REPO_ROOT = Path(__file__).resolve().parents[4]
STAGING_CHECKER = REPO_ROOT / "scripts" / "staging_db_read_check.py"

# The only Railway environment this module will resolve. Not a default that a
# caller can override to something else: `verified_staging_target` refuses any
# other value rather than tunnelling into it.
CANONICAL_RAILWAY_ENVIRONMENT = "staging"


class StagingTargetRefused(RuntimeError):
    """The target is not provably canonical Atlas staging. Fail closed."""


# 4D-1B. Last-resort scrubbing for text that is about to be printed.
#
# It is NOT the containment. Containment is that the tunnel URL is held in one
# field, never passed to a logger and never interpolated into a message - and
# that `railway connect`'s own stdout and stderr are captured by
# `open_tunnel` into a pipe this process reads, rather than inherited by the
# operator's terminal. This is the net under that: driver exception text,
# subprocess error text and anything else that reaches an operator goes
# through it, so a message that unexpectedly carries a DSN is redacted rather
# than printed.
#
# Deliberately narrow. It rewrites the two shapes a Postgres credential
# actually takes - userinfo in a URL, and a password assignment - and does not
# try to guess at arbitrary secrets, because a scrubber that claims to catch
# everything invites code that relies on it.
_CREDENTIAL_PATTERNS = (
    # scheme://user:password@host -> scheme://REDACTED@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/@]+@"), r"\1REDACTED@"),
    # password=... / PGPASSWORD=... / pwd=..., quoted or bare
    (
        re.compile(r"(?i)\b(pgpassword|password|pwd)\s*[=:]\s*(\"[^\"]*\"|'[^']*'|\S+)"),
        r"\1=REDACTED",
    ),
)


def scrub_credentials(text: str) -> str:
    """Redacts Postgres credentials from a string bound for an operator."""
    scrubbed = str(text)
    for pattern, replacement in _CREDENTIAL_PATTERNS:
        scrubbed = pattern.sub(replacement, scrubbed)
    return scrubbed


def load_staging_checker(path: Path | None = None) -> Any:
    """Imports scripts/staging_db_read_check.py as a module.

    Registered in sys.modules before execution, not after: the checker defines
    @dataclass types, and dataclasses resolves annotations through
    sys.modules[cls.__module__].
    """
    script = path or STAGING_CHECKER
    spec = importlib.util.spec_from_file_location("staging_db_read_check", script)
    if spec is None or spec.loader is None:
        raise StagingTargetRefused(f"cannot load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _connect_read_only(url: str, checker: Any) -> Any:
    """Collects facts over a server-enforced read-only session.

    Separated out so tests can substitute it without a live Postgres; the
    production path does exactly what the checker's own `main` does.
    """
    import psycopg

    with psycopg.connect(url, connect_timeout=15) as connection:
        connection.read_only = True
        return checker.collect_facts(connection)


@dataclass
class VerifiedStagingTarget:
    """A verified staging connection, and the tunnel keeping it open.

    `url` is a credential. Read it, do not print it - `redacted` is what goes
    in a log.
    """

    attestation: StagingTargetAttestation
    # repr=False is containment, not tidiness: a dataclass repr carrying a DSN
    # reaches an operator through any `%r`, any pytest assertion introspection
    # and any debug print, none of which the author of that line is thinking
    # about credentials when they write.
    url: str = field(repr=False)
    redacted: str
    _process: subprocess.Popen | None = field(default=None, repr=False)
    # 4D-1C. The checker's own `close_tunnel`, carried rather than re-derived:
    # it terminates the child, joins the drain thread reading its stdout and
    # closes the pipe, so cleanup here stays the same cleanup the tunnel
    # authority defines. None means "no drain to join" (a hand-built target in
    # a test), and plain terminate is then correct.
    _closer: Callable[[subprocess.Popen], None] | None = field(
        default=None, repr=False
    )

    def close(self) -> None:
        """Idempotent: the process is dropped before it is closed, so a second
        call - from a `finally` after an explicit close - is a no-op."""
        if self._process is None:
            return
        process, self._process = self._process, None
        if self._closer is not None:
            self._closer(process)
        else:  # pragma: no cover - only a target built without the checker
            process.terminate()

    def __enter__(self) -> "VerifiedStagingTarget":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def verified_staging_target(
    *,
    environment: str = CANONICAL_RAILWAY_ENVIRONMENT,
    service: str | None = None,
    checker: Any | None = None,
    collect: Callable[[str, Any], Any] | None = None,
    emit: Callable[[str], None] = print,
) -> VerifiedStagingTarget:
    """Opens, verifies and returns a canonical staging connection, or refuses.

    Order matters and is fail-closed throughout:

        1. the environment must be `staging` - anything else, including
           `production`, is refused before a tunnel is opened at all;
        2. a FRESH `railway connect --tunnel-only` SSH tunnel is resolved
           through the service (never a cached DATABASE_PUBLIC_URL, which is
           what resolved to the wrong database on 2026-08-21);
        3. every fingerprint in the checker must PASS;
        4. the alembic revision must be a single value the repo expects;
        5. only then is a second, fresh tunnel opened for the caller's work -
           the verification tunnel is not handed on after being closed.

    A refusal at any step raises `StagingTargetRefused` and leaves no tunnel
    behind. There is no fallback to another database.
    """
    checker = checker or load_staging_checker()

    wanted = (environment or "").strip().lower()
    if wanted in checker.REFUSED_ENVIRONMENTS:
        raise StagingTargetRefused(
            f"REFUSED: this runner never connects to {environment!r}."
        )
    if wanted != CANONICAL_RAILWAY_ENVIRONMENT:
        raise StagingTargetRefused(
            f"REFUSED: {environment!r} is not the canonical staging environment "
            f"({CANONICAL_RAILWAY_ENVIRONMENT!r})."
        )

    service = service or checker.DEFAULT_SERVICE
    collect = collect or _connect_read_only

    try:
        process, url = checker.open_tunnel(service, wanted)
    except Exception as exc:  # noqa: BLE001 - any failure here is a refusal
        # `open_tunnel` captures the Railway child's stdout AND stderr into a
        # pipe it reads itself, so nothing the CLI printed is in here - but
        # this is the boundary where a subprocess message would reach an
        # operator, so it is scrubbed on the way out regardless.
        raise StagingTargetRefused(
            "REFUSED: could not open a Railway staging tunnel: "
            f"{type(exc).__name__}: {scrub_credentials(str(exc))}"
        ) from None
    try:
        facts = collect(url, checker)
    except Exception as exc:  # noqa: BLE001 - a failed read is a failed check
        # `from None` deliberately: a chained traceback would carry the driver
        # exception, and driver exceptions are the most likely thing to quote
        # a DSN back at us.
        raise StagingTargetRefused(
            "REFUSED: could not read the staging database: "
            f"{type(exc).__name__}: {scrub_credentials(str(exc))}"
        ) from None
    finally:
        # The verification tunnel is closed through the same authority, so its
        # drain thread is joined rather than left to exit whenever it notices.
        _close = getattr(checker, "close_tunnel", None)
        if _close is not None:
            _close(process)
        else:  # pragma: no cover - a checker stub without the helper
            process.terminate()

    redacted = checker.redacted_target(url)
    expected = checker.expected_revisions_from_repo(str(REPO_ROOT))
    results = checker.evaluate(facts, expected)

    emit("== canonical staging target verification (fail-closed) ==")
    emit(f"  railway environment : {wanted}")
    emit(f"  railway service     : {service}")
    emit(f"  target              : {redacted}")
    for result in results:
        emit(f"  [{'PASS' if result.ok else 'FAIL'}] {result.name}: {result.detail}")

    checks = tuple((result.name, bool(result.ok)) for result in results)
    failed = [name for name, ok in checks if not ok]
    if failed:
        raise StagingTargetRefused(
            "REFUSED: this connection is NOT the canonical Atlas staging database "
            f"({', '.join(failed)} failed). No fallback."
        )

    revisions = tuple(facts.alembic_revisions)
    if len(revisions) != 1:
        raise StagingTargetRefused(
            "REFUSED: the database reports "
            f"{len(revisions)} alembic revisions; exactly one is required."
        )
    if revisions[0] not in expected:
        raise StagingTargetRefused(
            f"REFUSED: the database is at alembic revision {revisions[0]!r}, "
            f"which is not this checkout's expected head ({sorted(expected)}). "
            "Migrate first, or check out the matching commit."
        )

    attestation = StagingTargetAttestation(
        railway_environment=wanted,
        railway_service=service,
        database=facts.database or "",
        db_revision=revisions[0],
        checks=checks,
    )
    emit("  RESULT: PASS - canonical Atlas staging attested")
    emit("")

    # A fresh tunnel for the caller's work: the verification tunnel has been
    # terminated, and handing on a URL whose tunnel is closing is how a run
    # ends up reconnecting to something else.
    try:
        process, url = checker.open_tunnel(service, wanted)
    except Exception as exc:  # noqa: BLE001
        raise StagingTargetRefused(
            "REFUSED: the target verified, but the working tunnel could not be "
            f"opened: {type(exc).__name__}: {scrub_credentials(str(exc))}"
        ) from None
    return VerifiedStagingTarget(
        attestation=attestation,
        url=url,
        redacted=checker.redacted_target(url),
        _process=process,
        _closer=getattr(checker, "close_tunnel", None),
    )
