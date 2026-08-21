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
import subprocess
import sys
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
    "uq_source_card_mappings_lineage_identity",
    "uq_cards_identity",
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
    missing_con = [c for c in REQUIRED_CONSTRAINTS if c not in facts.constraints_present]
    missing_b = missing_rel + missing_con
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


def open_tunnel(service: str, environment: str) -> tuple[subprocess.Popen, str]:
    """Opens `railway connect --tunnel-only` and returns (process, url).

    The tunnel is an SSH tunnel resolved through the service itself, which is
    precisely why it is preferred: unlike DATABASE_PUBLIC_URL it cannot point at
    a stale public proxy. The URL is returned for use, never logged.
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
    )
    deadline = time.time() + TUNNEL_READY_TIMEOUT_S
    captured: list[str] = []
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        line = proc.stdout.readline() if proc.stdout else ""
        if not line:
            time.sleep(0.1)
            continue
        captured.append(line)
        match = re.match(r"\s*URL:\s*(\S+)\s*$", line)
        if match:
            return proc, match.group(1)

    proc.terminate()
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
            proc.terminate()

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
