#!/usr/bin/env python3
"""Fail-closed read-only connection validator for the canonical staging Postgres.

Why this exists
---------------
On 2026-08-21 an audit ran against what looked like a healthy staging database
and reported "0 rows" for every table. It was not staging. The Railway Postgres
service's public TCP proxy had been re-assigned (port 21415 -> 12258) and the
CLI, for a window, kept injecting the *stale* `DATABASE_PUBLIC_URL`. The old
port still had a live Postgres listening on it, so the connection **succeeded**,
authenticated, and reported `current_database() = 'railway'` - identical to the
real thing - while exposing an empty schema.

That is the failure mode this module exists to make impossible: a wrong
destination that answers instead of erroring. Neither the endpoint nor the
database name distinguishes the two (both are `railway` on `sakura.proxy.rlwy.net`),
so identity here is proven by **schema fingerprint**, never by reachability.

Two rules follow from the incident, and both are enforced below:

1. **Zero rows is never proof of a valid database.** An empty result set is
   exactly what the wrong database returns. Emptiness is treated as failure for
   tables that must never be empty, and `collection_items` - which is
   legitimately empty on staging - is deliberately excluded from that check.
2. **Prefer a freshly-resolved tunnel over any cached variable.**
   `railway connect --tunnel-only` resolves through the service itself over SSH,
   so it cannot land on a stale public proxy. `DATABASE_PUBLIC_URL` can, and did.

Scope
-----
This is a *connection validator*, not a database administration tool and not a
general-purpose SQL runner. It issues a fixed set of catalogue introspection
queries and counts, inside a read-only session, and exits non-zero if anything
fails. It has no code path that writes.

Usage
-----
    # Normal use: open a fresh SSH tunnel to staging and validate it.
    python scripts/staging_db_read_check.py

    # Validate a connection URL already present in the environment (CI, or the
    # negative control that proves a wrong database is rejected). The URL is
    # read from the named variable and never printed.
    DATABASE_URL=... python scripts/staging_db_read_check.py --url-env DATABASE_URL

Exit codes
----------
    0  every fingerprint passed - the connection is the Atlas staging database
    1  a fingerprint failed - do NOT trust query results from this connection
    2  usage/operational error (refused environment, tunnel failure, ...)
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# --- What "this is Atlas staging" means -------------------------------------
#
# Five independent fingerprints. They are deliberately of different *kinds* -
# tables, named constraints/indexes, columns, migration revision, row-count
# invariants - so that no single accident (an empty database, a restored
# backup, a partially-migrated database, another project's database that
# happens to share a table name) can satisfy all five.

# Fingerprint A - tables that must exist.
REQUIRED_TABLES = (
    "alembic_version",
    "canonical_cards",
    "card_prints",
    "cards",
    "price_observations",
    "source_card_mappings",
    "sources",
    "collection_items",
    "market_index_snapshots",
)

# Fingerprint B - named constraints and indexes unique to this schema. A
# database with the right table names but the wrong provenance (a scaffold, a
# different project, a hand-made fixture) will not carry these.
REQUIRED_RELATIONS = (
    "uq_card_prints_active_verified_identity",
    "uq_market_index_snapshots_print_date",
    "ix_market_index_snapshots_print_calculated",
    "uq_cards_identity",
)

# Fingerprint B, renamed-relation groups: at least one name from each group
# must be present. A fingerprint's job is to prove provenance, not to pin a
# schema version, so a relation that a migration RENAMES has to be accepted
# under either name - otherwise this checker fails on exactly the databases it
# is meant to bracket, before and after the upgrade.
#
# The mapping lineage key is the current case. b858237e3706 created it as
# (id, card_print_id, card_id, source_id); c9f31e2a7d04 replaced it with
# (id, card_print_id, source_id) under a new name, because card_id became a
# nullable legacy column and PostgreSQL FKs are MATCH SIMPLE - leaving it in
# the key would have switched the composite FK off for every
# print-authoritative row. Either name is equally good evidence that this is
# Atlas staging.
REQUIRED_RELATION_ALTERNATIVES = (
    (
        "uq_source_card_mappings_lineage_identity",
        "uq_source_card_mappings_print_lineage_identity",
    ),
)
REQUIRED_CONSTRAINTS = (
    "ck_card_prints_verified_requires_fields",
    "ck_market_index_snapshots_value_presence",
    "ck_market_index_snapshots_range_pairing",
    "ck_collection_items_status",
)

# Fingerprint C - columns carrying the print-lineage model. These are what make
# the database *this* Atlas, at a schema version that understands exact prints.
REQUIRED_COLUMNS = (
    ("price_observations", "card_id"),
    ("price_observations", "card_print_id"),
    ("card_prints", "artwork_key"),
    ("card_prints", "treatment"),
    ("card_prints", "verification_status"),
    ("market_index_snapshots", "snapshot_date"),
    ("market_index_snapshots", "provenance"),
)

# Fingerprint E - tables that must NOT be empty. Emptiness is the signature of
# the wrong database, so it is a failure here.
#
# `collection_items` is deliberately absent: it is genuinely 0 on staging (see
# the 4A-1 Collection audit), and asserting it non-empty would fail against the
# real database - the precise inversion of the bug this module guards.
NON_EMPTY_TABLES = ("canonical_cards", "card_prints", "sources")

# Environments this tool will talk to. Production is refused outright, with no
# override flag: this is a read-only checker for staging and nothing about it
# needs to reach production.
ALLOWED_ENVIRONMENTS = ("staging",)
REFUSED_ENVIRONMENTS = ("production", "prod")

DEFAULT_SERVICE = "Postgres"
TUNNEL_READY_TIMEOUT_S = 60


@dataclass
class Facts:
    """Everything read from the connection, before any judgement is applied.

    Separating collection from evaluation is what makes the rules testable
    without a live database - see tests/test_staging_db_read_check.py.
    """

    database: str | None = None
    transaction_read_only: str | None = None
    alembic_revisions: tuple[str, ...] = ()
    tables_present: frozenset[str] = frozenset()
    relations_present: frozenset[str] = frozenset()
    constraints_present: frozenset[str] = frozenset()
    columns_present: frozenset[tuple[str, str]] = frozenset()
    row_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def evaluate(facts: Facts, expected_revisions: frozenset[str]) -> list[CheckResult]:
    """Applies every fingerprint to collected `facts`. Pure - no I/O.

    Returns one CheckResult per fingerprint, in report order. The caller decides
    what to do with them; nothing here exits or prints.
    """
    results: list[CheckResult] = []

    results.append(
        CheckResult(
            "session is read-only",
            facts.transaction_read_only == "on",
            f"transaction_read_only={facts.transaction_read_only!r} (want 'on')",
        )
    )

    missing_tables = [t for t in REQUIRED_TABLES if t not in facts.tables_present]
    results.append(
        CheckResult(
            "fingerprint A - required tables",
            not missing_tables,
            "all present" if not missing_tables else f"MISSING: {', '.join(missing_tables)}",
        )
    )

    missing_rel = [r for r in REQUIRED_RELATIONS if r not in facts.relations_present]
    missing_alt = [
        " or ".join(group)
        for group in REQUIRED_RELATION_ALTERNATIVES
        if not any(name in facts.relations_present for name in group)
    ]
    missing_con = [c for c in REQUIRED_CONSTRAINTS if c not in facts.constraints_present]
    missing_b = missing_rel + missing_alt + missing_con
    results.append(
        CheckResult(
            "fingerprint B - named indexes/constraints",
            not missing_b,
            "all present" if not missing_b else f"MISSING: {', '.join(missing_b)}",
        )
    )

    missing_cols = [
        f"{t}.{c}" for (t, c) in REQUIRED_COLUMNS if (t, c) not in facts.columns_present
    ]
    results.append(
        CheckResult(
            "fingerprint C - print-lineage columns",
            not missing_cols,
            "all present" if not missing_cols else f"MISSING: {', '.join(missing_cols)}",
        )
    )

    revs = set(facts.alembic_revisions)
    rev_ok = bool(revs) and revs <= set(expected_revisions)
    results.append(
        CheckResult(
            "fingerprint D - alembic revision",
            rev_ok,
            f"found={sorted(revs) or 'NONE'} expected={sorted(expected_revisions)}",
        )
    )

    empty = [t for t in NON_EMPTY_TABLES if facts.row_counts.get(t, 0) <= 0]
    results.append(
        CheckResult(
            "fingerprint E - non-empty invariants",
            not empty,
            (
                ", ".join(f"{t}={facts.row_counts.get(t, 0)}" for t in NON_EMPTY_TABLES)
                if not empty
                else f"EMPTY (wrong database?): {', '.join(empty)}"
            )
        )
    )

    return results


def collect_facts(conn) -> Facts:
    """Runs the fixed introspection queries. Read-only by construction: every
    statement here is a SELECT or a SHOW."""
    facts = Facts()
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        facts.database = cur.fetchone()[0]

        cur.execute("SHOW transaction_read_only")
        facts.transaction_read_only = cur.fetchone()[0]

        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
        facts.tables_present = frozenset(r[0] for r in cur.fetchall())

        cur.execute("SELECT relname FROM pg_class WHERE relkind IN ('i', 'r')")
        facts.relations_present = frozenset(r[0] for r in cur.fetchall())

        cur.execute("SELECT conname FROM pg_constraint")
        facts.constraints_present = frozenset(r[0] for r in cur.fetchall())

        cur.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        )
        facts.columns_present = frozenset((r[0], r[1]) for r in cur.fetchall())

        if "alembic_version" in facts.tables_present:
            cur.execute("SELECT version_num FROM alembic_version")
            facts.alembic_revisions = tuple(r[0] for r in cur.fetchall())

        for table in NON_EMPTY_TABLES:
            if table in facts.tables_present:
                # Table names come from this module's own constants, never from
                # input - no interpolation of untrusted values.
                cur.execute(f"SELECT count(*) FROM {table}")
                facts.row_counts[table] = cur.fetchone()[0]
            else:
                facts.row_counts[table] = 0

    return facts


def expected_revisions_from_repo(repo_root: str) -> frozenset[str]:
    """The alembic head(s) this checkout expects staging to be at.

    Read from the migration scripts themselves rather than hardcoded, so the
    expectation follows the repo instead of drifting behind it.
    """
    versions_dir = os.path.join(repo_root, "services", "api", "alembic", "versions")
    revisions: dict[str, str | None] = {}
    for name in os.listdir(versions_dir):
        if not name.endswith(".py"):
            continue
        text = open(os.path.join(versions_dir, name), encoding="utf-8").read()
        rev = re.search(r"^revision(?::\s*str)?\s*=\s*[\"']([^\"']+)[\"']", text, re.M)
        down = re.search(
            r"^down_revision(?::\s*[^=]+)?\s*=\s*(?:[\"']([^\"']+)[\"']|None)", text, re.M
        )
        if rev:
            revisions[rev.group(1)] = down.group(1) if down else None
    parents = {d for d in revisions.values() if d}
    return frozenset(r for r in revisions if r not in parents)


def redacted_target(url: str) -> str:
    """A printable description of where we connected - host, port, database.
    Never the user, never the password, never the URL."""
    parts = urlsplit(url)
    return f"{parts.hostname}:{parts.port}/{(parts.path or '/').lstrip('/')}"


# Attribute the drain thread is parked on, so `close_tunnel` can join it
# without changing what `open_tunnel` returns. Private by name: nothing outside
# this module reads it except `close_tunnel`.
DRAIN_ATTR = "_atlas_tunnel_drain"
DRAIN_THREAD_NAME = "railway-tunnel-drain"
DRAIN_CHUNK = 65536
DRAIN_JOIN_TIMEOUT_S = 5.0

# 4D-4. The process-group id of the tunnel, captured at spawn and parked on the
# process object.
#
# WHY IT IS STORED RATHER THAN LOOKED UP. `railway connect` is a node process
# that spawns `ssh -L ...` and lets it do the forwarding. When cleanup runs the
# LEADER IS USUALLY ALREADY GONE - it answers SIGTERM promptly, and `ssh` does
# not - so `os.getpgid(proc.pid)` raises ProcessLookupError at exactly the
# moment the group id is needed. Captured at spawn, the id stays valid for as
# long as any member of the group is alive, which is precisely the window in
# which we need to signal it.
PGID_ATTR = "_atlas_tunnel_pgid"
# How long the group is given to die between escalation steps.
GROUP_SIGNAL_POLL_S = 0.05

# WHY THE GROUP IS NOT THE WHOLE STORY. Measured against the real CLI on
# 2026-08-25: `railway connect` spawns its `ssh -L` with setpgid, so the ssh
# ends up in ITS OWN process group - but, because it does not call setsid, it
# stays in the SESSION `start_new_session` created for the tunnel:
#
#     railway  pid=273096  pgid=273096  sid=273096   <- leader
#     ssh      pid=273182  pgid=273182  sid=273096   <- own group, same session
#
# So `killpg(273096)` reaches the leader and misses the forward. The session is
# the boundary that actually contains the tunnel, and on Linux its members are
# enumerable from /proc. `killpg` is still issued first - it is atomic and
# covers everything that stayed in the group - and the sweep catches the rest.
PROC_FS = "/proc"

# The one line `open_tunnel` cares about. Compiled once, used only by the
# reader thread.
URL_LINE_RE = re.compile(r"\s*URL:\s*(\S+)\s*$")

# 4D-4B. Cap on the partial line held while looking for the URL. Railway's
# `URL:` line is a couple of hundred bytes; anything past this is not it, so
# the buffer is dropped rather than grown. Bounds memory against a child that
# writes without ever emitting a newline.
PRE_URL_SCAN_LIMIT = 64 * 1024


def _drain(stream) -> None:
    """Consume and discard everything the child writes after the URL line.

    WHY THIS EXISTS. `open_tunnel` returns as soon as it has parsed the `URL:`
    line, and the tunnel process keeps running - and keeps writing. Nothing was
    reading the far end of that pipe, so a chatty `railway connect` would fill
    the OS pipe buffer (~64 KiB on Linux) and then BLOCK on its next write. A
    blocked tunnel process stops forwarding, and an import that had already
    verified its target would stall mid-run rather than fail cleanly.

    Reads in bounded chunks rather than lines: a child that emits a very long
    line without a newline would otherwise buffer that whole line in memory.
    Nothing is returned, stored, printed or logged - the chunk is dropped on
    the next iteration - so the credential-bearing lines Railway prints after
    the URL are consumed and forgotten, never accumulated.

    Ends at EOF, which is what the child's exit produces. `ValueError` and
    `OSError` are the two ways a read can fail when the stream is closed under
    a blocked reader during shutdown; neither is reported, and neither carries
    consumed text, because no consumed text is ever put into a message.
    """
    try:
        while stream.read(DRAIN_CHUNK):
            pass
    except (ValueError, OSError):
        return


class _TunnelHandshake:
    """Where the reader thread publishes the URL, and how `open_tunnel` waits.

    4D-4B. The caller no longer reads the pipe at all, so its deadline is an
    `Event.wait(timeout)` - one blocking call that the OS wakes, with no
    polling and no way to overrun. `settled` is set on EITHER outcome, so a
    child that dies without ever announcing a URL refuses immediately rather
    than making the operator wait out the full timeout.
    """

    __slots__ = ("_url", "_settled")

    def __init__(self) -> None:
        self._url: str | None = None
        self._settled = threading.Event()

    def publish(self, url: str) -> None:
        self._url = url
        self._settled.set()

    def settle(self) -> None:
        """Reader finished without a URL (EOF or read error). Unblocks."""
        self._settled.set()

    def wait(self, timeout: float) -> bool:
        return self._settled.wait(timeout)

    @property
    def url(self) -> str | None:
        return self._url


def _scan_for_url(fd: int, handshake: _TunnelHandshake) -> bool:
    """Phase 1: find the `URL:` line on `fd`, retaining nothing else.

    Reads with `os.read`, not `readline`. That is the whole point: `readline`
    returns only at a newline, so a child that writes a partial line and then
    goes quiet blocks the reader indefinitely - and before 4D-4B that reader
    was the CALLER, which is how TUNNEL_READY_TIMEOUT_S became advisory.
    `os.read` returns as soon as ANY bytes are available, so this loop makes
    progress on whatever arrives and never waits for punctuation.

    Only one partial line is ever held, and only until the next newline.
    PRE_URL_SCAN_LIMIT caps even that: a child emitting megabytes without a
    newline cannot grow this buffer, because a run that long is not a `URL:`
    line and is dropped. Nothing scanned is returned, stored, printed or
    logged - the credential-bearing preamble is matched against and forgotten.

    Returns True once the URL is published, False at EOF or on a read error.
    """
    buffered = b""
    while True:
        try:
            chunk = os.read(fd, DRAIN_CHUNK)
        except (OSError, ValueError):
            return False
        if not chunk:
            return False  # EOF: the child exited without announcing a URL
        buffered += chunk
        while True:
            newline = buffered.find(b"\n")
            if newline < 0:
                break
            line = buffered[:newline]
            buffered = buffered[newline + 1 :]
            match = URL_LINE_RE.match(line.decode("utf-8", "replace"))
            if match:
                handshake.publish(match.group(1))
                return True
        if len(buffered) > PRE_URL_SCAN_LIMIT:
            # Far too long to be the line we want. Drop it rather than grow.
            buffered = b""


def _read_tunnel(stream, handshake: _TunnelHandshake) -> None:
    """The SINGLE owner of the tunnel's stdout, for the tunnel's whole life.

    One thread, two phases: scan for the URL, then discard forever. The pipe
    is never handed between competing readers - before 4D-4B the caller read
    it until the URL and a drain thread took over afterwards, and a fd with two
    readers is what makes "who is blocked on this?" unanswerable.
    """
    found = False
    try:
        found = _scan_for_url(stream.fileno(), handshake)
    finally:
        # Unblocks the caller on every path, including a read error.
        handshake.settle()
    if found:
        _drain(stream)


def _start_drain(
    proc: subprocess.Popen, handshake: _TunnelHandshake
) -> threading.Thread | None:
    """Starts the reader/drain and parks it on the process for `close_tunnel`.

    Daemon, so a reader blocked on a child that outlives us can never hold up
    interpreter shutdown.
    """
    if proc.stdout is None:  # pragma: no cover - always a pipe here
        return None
    thread = threading.Thread(
        target=_read_tunnel,
        args=(proc.stdout, handshake),
        name=DRAIN_THREAD_NAME,
        daemon=True,
    )
    thread.start()
    setattr(proc, DRAIN_ATTR, thread)
    return thread


def tunnel_pgid(proc: subprocess.Popen) -> int | None:
    """The process-group id captured for this tunnel, or None.

    None means the tunnel was not spawned by `open_tunnel` (a hand-built Popen
    in a test, or a platform without sessions), and cleanup falls back to
    signalling the leader alone.
    """
    return getattr(proc, PGID_ATTR, None)


def _safe_group(proc: subprocess.Popen) -> int | None:
    """The stored PGID, but only when it is safe to signal.

    A tunnel whose group or session is OUR OWN is never signalled: neither
    `os.killpg` nor the session sweep excludes the caller, so a SIGKILL there
    would take down the importer - or the test runner - along with the tunnel.
    That can only happen if the new session was never created, in which case
    leader-only termination is both correct and all that was ever available.
    """
    pgid = tunnel_pgid(proc)
    if pgid is None:
        return None
    try:
        if pgid == os.getpgid(0) or pgid == os.getsid(0):
            return None
    except OSError:  # pragma: no cover - no pgid/sid concept
        return None
    return pgid


def _signal_group(pgid: int | None, sig: int) -> bool:
    """Signals every member of the tunnel group. False if it is already gone.

    ESRCH is the ordinary outcome of closing a tunnel that has already died,
    and EPERM of one we may no longer signal; neither is an error worth
    raising out of a cleanup path, and neither carries any credential.
    """
    if pgid is None:
        return False
    try:
        os.killpg(pgid, sig)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - not ours to signal
        return False


def _session_members(sid: int | None) -> list[int]:
    """Live pids in the tunnel's session, read from /proc. Never includes us.

    This is what reaches the `ssh` that put itself in its own process group.
    Anything unreadable is skipped rather than raised on: a pid can exit
    between listing and reading, and a cleanup path must not fail for it.
    """
    if sid is None:
        return []
    try:
        own_sid = os.getsid(0)
    except OSError:  # pragma: no cover - no session concept
        return []
    if sid == own_sid:  # never sweep our own session
        return []
    try:
        entries = os.listdir(PROC_FS)
    except OSError:  # pragma: no cover - no procfs
        return []
    own_pid = os.getpid()
    members: list[int] = []
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == own_pid:
            continue
        try:
            with open(f"{PROC_FS}/{pid}/stat", encoding="utf-8") as handle:
                stat = handle.read()
        except (OSError, ValueError):
            continue
        # "pid (comm) state ppid pgrp session ..." - comm may contain spaces
        # and parentheses, so split after the LAST ')'.
        try:
            fields = stat.rsplit(")", 1)[1].split()
            if fields[0] == "Z":  # a reaped corpse is not a survivor
                continue
            if int(fields[3]) == sid:
                members.append(pid)
        except (IndexError, ValueError):  # pragma: no cover - malformed row
            continue
    return members


def _signal_tunnel(proc: subprocess.Popen, sig: int) -> None:
    """Signals the tunnel's process group AND its wider session.

    The group first, because `killpg` is one atomic call that covers every
    process which stayed put. Then the session sweep, for the ones that gave
    themselves a new group - which is exactly what Railway's `ssh` does.
    """
    pgid = _safe_group(proc)
    _signal_group(pgid, sig)
    for pid in _session_members(pgid):
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            continue


def _tunnel_gone(proc: subprocess.Popen) -> bool:
    """Whether nothing of the tunnel remains - group or session."""
    pgid = _safe_group(proc)
    if pgid is None:
        return True
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        pass
    except PermissionError:  # pragma: no cover - exists but not ours
        return False
    else:
        return False
    return not _session_members(pgid)


def _await_tunnel_exit(proc: subprocess.Popen, timeout: float) -> bool:
    """Polls until the tunnel is gone or the budget runs out. Never blocks."""
    deadline = time.time() + max(timeout, 0.0)
    while True:
        if _tunnel_gone(proc):
            return True
        if time.time() >= deadline:
            return _tunnel_gone(proc)
        time.sleep(GROUP_SIGNAL_POLL_S)


def _reap_leader(proc: subprocess.Popen, timeout: float) -> bool:
    """Bounded `wait`. Already-reaped leaders return immediately."""
    try:
        proc.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False
    except (OSError, ValueError):  # pragma: no cover - nothing left to wait on
        return True


def close_tunnel(proc: subprocess.Popen, timeout: float = DRAIN_JOIN_TIMEOUT_S) -> None:
    """Terminates a tunnel AND ITS WHOLE PROCESS GROUP. Idempotent, bounded.

    4D-4. The previous implementation signalled the leader alone, and on a real
    Railway tunnel that was never enough: `railway connect` dies from SIGTERM
    while the `ssh -L` it spawned keeps running - and keeps the inherited pipe
    WRITE END open. The drain thread therefore never reached EOF, its join
    expired with the reader still inside `read()`, and `proc.stdout.close()`
    then blocked forever on the `BufferedReader` lock that reader still held.
    A hang, an orphaned forward into staging, and - on the apply path - a
    committed import whose report never printed.

    So the unit of cleanup is the tunnel's GROUP AND SESSION, in this order:

        1. SIGTERM the entire group, addressed by the id captured at spawn
           (not looked up now: the leader is usually already gone), then sweep
           the session for members that gave themselves a different group -
           which is what Railway's `ssh -L` does;
        2. reap the leader and give the tunnel a bounded interval to exit;
        3. if anything survives, SIGKILL THE SAME group and session and reap;
        4. only then join the drain, which by now has its EOF;
        5. only then close the pipe, with the reader provably returned.

    Every step is bounded: `wait`, the liveness polls, the join and the close
    can none of them block indefinitely. The timeout path still leaves zero
    tunnel descendants, because escalation happens before the join, not after.
    """
    pgid = _safe_group(proc)

    # 1. SIGTERM the whole tunnel.
    if pgid is None:
        # No group to address - signal the leader alone. This is the
        # pre-4D-4 behaviour, kept only for processes we did not spawn.
        try:
            proc.terminate()
        except (OSError, ProcessLookupError):  # pragma: no cover - already gone
            pass
    else:
        _signal_tunnel(proc, signal.SIGTERM)

    # 2. Reap the leader, then let the rest drain out. Reaping first matters:
    #    an unreaped zombie leader still answers `killpg(0)`, so the tunnel
    #    would look alive when only a corpse remained.
    _reap_leader(proc, timeout)
    gone = _await_tunnel_exit(proc, timeout)

    # 3. Escalate on the SAME group and session. This is what reaches an `ssh`
    #    that ignored - or, in its own group, never received - the first signal.
    if not gone:
        if pgid is None:
            try:
                proc.kill()
            except (OSError, ProcessLookupError):  # pragma: no cover
                pass
        else:
            _signal_tunnel(proc, signal.SIGKILL)
        _reap_leader(proc, timeout)
        _await_tunnel_exit(proc, timeout)

    # 4. The group is gone, so the write end is closed and the drain has its
    #    EOF. Join is bounded regardless.
    thread = getattr(proc, DRAIN_ATTR, None)
    if thread is not None:
        thread.join(timeout=timeout)
        if thread.is_alive():  # pragma: no cover - a writer outside the group
            # Do NOT close the pipe under a blocked reader: that is exactly the
            # deadlock this function exists to remove. Leave the fd open, leave
            # the (daemon) thread parked, and let a later call retry.
            return
        setattr(proc, DRAIN_ATTR, None)

    # 5. Sole owner of the fd now.
    if proc.stdout is not None:
        try:
            proc.stdout.close()
        except (ValueError, OSError):  # pragma: no cover
            pass


def open_tunnel(service: str, environment: str) -> tuple[subprocess.Popen, str]:
    """Opens `railway connect --tunnel-only` and returns (process, url).

    The tunnel is an SSH tunnel resolved through the service itself, which is
    precisely why it is preferred: unlike DATABASE_PUBLIC_URL it cannot point at
    a stale public proxy. The URL is returned for use, never logged.

    The child's stdout and stderr are merged into one pipe: nothing Railway
    prints - host, port, user, password, the full DSN - is inherited by the
    operator's terminal. Only the `URL:` line is parsed out. The rest is
    consumed and discarded so the tunnel cannot block on a full pipe; close it
    with `close_tunnel`.

    4D-4B. THE DEADLINE IS REAL NOW. This function no longer reads the pipe.
    A single reader thread owns it for the tunnel's whole life - scanning for
    the URL, then draining - and publishes what it finds through a
    `_TunnelHandshake`. All this function does is `Event.wait(timeout)`: one
    blocking call, woken by the OS, with no polling and no way to overrun.

    Before, the caller drove `proc.stdout.readline()` in a loop that checked
    the deadline only BETWEEN lines. `readline` returns at a newline, so a
    child that stayed alive and wrote nothing - or wrote a partial line and
    fell silent - blocked the caller indefinitely and TUNNEL_READY_TIMEOUT_S
    meant nothing. That is the gap this closes.

    4D-4. The tunnel is spawned in ITS OWN SESSION, so `railway connect` leads
    a process group that every process it spawns - notably the `ssh -L` doing
    the actual forwarding - inherits. That group is the unit `close_tunnel`
    signals, and its id is recorded on the process object here, at the one
    moment it is guaranteed to be knowable. No shell is involved: the argument
    list is unchanged, and `start_new_session` is a fork-time setting, not a
    command.
    """
    proc = subprocess.Popen(
        [
            "railway", "connect", service,
            "--environment", environment,
            "--tunnel-only",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        # setsid in the child between fork and exec: the child becomes both
        # session leader and process-group leader, so its pgid == its pid.
        start_new_session=True,
    )
    # Recorded now, not derived later: by cleanup time the leader is usually
    # gone and `os.getpgid(proc.pid)` would raise. The value is the leader's
    # own pid by construction of start_new_session.
    setattr(proc, PGID_ATTR, proc.pid)

    handshake = _TunnelHandshake()
    _start_drain(proc, handshake)
    # One bounded wait. Returns early when the reader publishes a URL, and
    # early again if the child dies without one - only a live-but-silent child
    # actually spends the full budget.
    handshake.wait(TUNNEL_READY_TIMEOUT_S)
    url = handshake.url
    if url is not None:
        return proc, url

    # Timed out, or the child exited first. Either way this is a refusal, and
    # it goes through the same process/session authority every other exit path
    # uses - so a tunnel that never became usable still leaves no leader, no
    # ssh, and no reader thread behind.
    close_tunnel(proc)
    raise RuntimeError(
        "railway connect did not report a tunnel URL within "
        f"{TUNNEL_READY_TIMEOUT_S}s (is the CLI logged in and the project linked?)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--environment", default="staging",
        help="Railway environment to tunnel into (default: staging). Production is refused.",
    )
    parser.add_argument(
        "--service", default=DEFAULT_SERVICE,
        help=f"Railway database service name (default: {DEFAULT_SERVICE}).",
    )
    parser.add_argument(
        "--url-env", default=None, metavar="VARNAME",
        help="Validate the connection URL held in this environment variable instead of "
             "opening a tunnel. The value is read, never printed. Use for CI and for the "
             "negative control that proves a wrong database is rejected.",
    )
    args = parser.parse_args(argv)

    environment = args.environment.strip().lower()
    if environment in REFUSED_ENVIRONMENTS:
        print(f"REFUSED: this checker never connects to '{args.environment}'.", file=sys.stderr)
        return 2
    if args.url_env is None and environment not in ALLOWED_ENVIRONMENTS:
        print(
            f"REFUSED: unexpected Railway environment '{args.environment}' "
            f"(allowed: {', '.join(ALLOWED_ENVIRONMENTS)}).",
            file=sys.stderr,
        )
        return 2

    try:
        import psycopg
    except ImportError:
        print("FAIL: psycopg is not installed (pip install -r services/api/requirements.txt).",
              file=sys.stderr)
        return 2

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    expected = expected_revisions_from_repo(repo_root)

    proc: subprocess.Popen | None = None
    if args.url_env:
        url = os.environ.get(args.url_env, "")
        if not url:
            print(f"FAIL: ${args.url_env} is empty or unset.", file=sys.stderr)
            return 2
        method = f"URL from ${args.url_env} (NOT a freshly-resolved tunnel)"
    else:
        try:
            proc, url = open_tunnel(args.service, args.environment)
        except (RuntimeError, FileNotFoundError) as exc:
            print(f"FAIL: could not open a Railway tunnel: {exc}", file=sys.stderr)
            return 2
        method = f"fresh `railway connect {args.service} --tunnel-only` SSH tunnel"

    print("== Staging DB read check ==")
    print(f"  method       : {method}")
    print(f"  environment  : {args.environment}")
    print(f"  target       : {redacted_target(url)}")

    try:
        # read_only is set before the first transaction begins, so every
        # statement this process can issue is rejected by the server if it
        # attempts a write. autocommit keeps us out of a long-lived
        # transaction while introspecting.
        with psycopg.connect(url, connect_timeout=15) as conn:
            conn.read_only = True
            facts = collect_facts(conn)
    except Exception as exc:  # noqa: BLE001 - any failure here is a failed check
        print(f"  FAIL: could not query the database: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1
    finally:
        if proc is not None:
            close_tunnel(proc)

    print(f"  database     : {facts.database}")
    print()

    results = evaluate(facts, expected)
    for res in results:
        print(f"  [{'PASS' if res.ok else 'FAIL'}] {res.name}: {res.detail}")

    print()
    if all(r.ok for r in results):
        print("RESULT: PASS - this connection is the Atlas staging database.")
        print("Counts are identity evidence only, not an audit result.")
        return 0

    print("RESULT: FAIL - this connection is NOT the Atlas staging database.", file=sys.stderr)
    print("Discard any query results taken from it.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
