"""CLI: plan - never perform - the import of exact Japanese Bandai prints.

    python -m app.plan_canonical_print_import --card-code OP01-001
    python -m app.plan_canonical_print_import --series 550101 --json
    python -m app.plan_canonical_print_import --card-code OP04-004 --staging

There is no --apply, no --write, no --persist and no --force. This module
imports nothing that writes, opens its database session read-only, and the
planner it calls (app.services.print_import_planner) contains no INSERT,
UPDATE or DELETE. A write path cannot be reached from here by any flag.

Where the data comes from
-------------------------
Two reads, both from Bandai's Japanese official Card List:

  --series <id>       one product's own catalogue page
  --card-code <CODE>  the catalogue's freewords search, which is what exposes
                      every official artwork of a card *across* products - the
                      only way to see that OP01-001 has artworks in three
                      different products, one of them uncoded.

Asset digests
-------------
By default each planned artwork is fetched once and hashed, because a verified
print needs `artwork_key` evidence and because a digest is the only way to
notice that Bandai has replaced the bytes behind an address already recorded
against an existing print. `--no-fetch-assets` skips it, and every plan that
then lacks a digest is downgraded to needs_review rather than waved through.

Talking to staging
------------------
`--staging` is the only way to reach the canonical staging database, and it
refuses to proceed unless the established fail-closed verification passes
first: a fresh `railway connect --tunnel-only` SSH tunnel (never a cached
DATABASE_PUBLIC_URL, which has silently resolved to the wrong database
before), then the full fingerprint check from scripts/staging_db_read_check.py
- reused, not reimplemented.

Exit codes
----------
    0  a plan was produced
    1  the staging connection failed verification, or a fetch failed
    2  usage error
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import urllib.request
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.settings import normalize_database_url
from app.services.official_cardlist import (
    CARD_LIST_BASE_URL,
    SOURCE_CATALOGUE,
    OfficialCardListPage,
    card_list_url,
    parse_card_list,
)
from app.services.print_import_planner import ImportPlan, plan_entries

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

TIMEOUT_SECONDS = 45.0
USER_AGENT = "CardPirateAtlas-print-import-planner/1.0"

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_CHECKER = REPO_ROOT / "scripts" / "staging_db_read_check.py"


def emit(line: str = "") -> None:
    print(line, flush=True)


# --- official catalogue reads ------------------------------------------------


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def fetch_series_page(series_id: str) -> OfficialCardListPage:
    url = card_list_url(series_id)
    return parse_card_list(_get(url).decode("utf-8", "replace"), series_id, base_url=url)


def fetch_card_code_page(card_code: str) -> OfficialCardListPage:
    """Every official artwork of one card, across every product.

    The freewords result is the same markup as a series page, so it parses
    with the same reader; it simply has no series of its own, which is why the
    page's series_id is empty and each entry's product is resolved from its
    own 入手情報 line instead.
    """
    url = f"{CARD_LIST_BASE_URL}?freewords={card_code}&search=true"
    return parse_card_list(_get(url).decode("utf-8", "replace"), "", base_url=url)


class AssetDigests:
    """Fetches and caches SHA-256 for official assets. Read-only by nature."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._cache: dict[str, str | None] = {}
        self.fetched = 0
        self.failures: list[str] = []

    def __call__(self, url: str) -> str | None:
        if not self.enabled or not url:
            return None
        if url in self._cache:
            return self._cache[url]
        try:
            digest = hashlib.sha256(_get(url)).hexdigest()
            self.fetched += 1
        except Exception as exc:  # noqa: BLE001 - a failed fetch is missing evidence
            self.failures.append(f"{url}: {type(exc).__name__}: {exc}")
            digest = None
        self._cache[url] = digest
        return digest


# --- database session, read-only ---------------------------------------------


def _load_staging_checker():
    spec = importlib.util.spec_from_file_location("staging_db_read_check", STAGING_CHECKER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {STAGING_CHECKER}")
    module = importlib.util.module_from_spec(spec)
    # Register before executing: the checker defines @dataclass types, and
    # dataclasses resolves annotations through sys.modules[cls.__module__].
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verified_staging_url() -> str:
    """A freshly-tunnelled staging URL that has passed every fingerprint.

    Reuses scripts/staging_db_read_check.py wholesale - its tunnel opener, its
    fact collection and its rules - so this CLI cannot drift into a weaker
    definition of "this is really staging" than the established one.
    """
    checker = _load_staging_checker()
    process, url = checker.open_tunnel(checker.DEFAULT_SERVICE, "staging")
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=15) as connection:
            connection.read_only = True
            facts = checker.collect_facts(connection)
    finally:
        process.terminate()

    expected = checker.expected_revisions_from_repo(str(REPO_ROOT))
    results = checker.evaluate(facts, expected)
    emit("== staging read verification (fail-closed) ==")
    emit(f"  target : {checker.redacted_target(url)}")
    for result in results:
        emit(f"  [{'PASS' if result.ok else 'FAIL'}] {result.name}: {result.detail}")
    if not all(result.ok for result in results):
        raise RuntimeError(
            "staging read verification FAILED - refusing to plan against this connection"
        )
    emit("  RESULT: PASS")
    emit()
    # The verification tunnel is closed; open a fresh one for the plan itself
    # rather than reusing a URL whose tunnel has just been terminated.
    process, url = checker.open_tunnel(checker.DEFAULT_SERVICE, "staging")
    _KEEP_ALIVE.append(process)
    return url


# Tunnels must outlive verified_staging_url(); the process objects are parked
# here so they are not garbage collected mid-run.
_KEEP_ALIVE: list = []


def read_only_sessionmaker(url: str):
    """A sessionmaker whose every connection refuses to write.

    Belt and braces: the planner has no write path, and the server is told to
    reject one anyway. On PostgreSQL that is enforced by the server itself, so
    a stray write raises rather than silently succeeding.
    """
    # The tunnel hands back Railway's bare postgresql:// URL, which SQLAlchemy
    # would route to psycopg2. This service runs psycopg 3, and the repo
    # already has one normalizer for exactly that - reused rather than
    # re-spelled here.
    engine = create_engine(normalize_database_url(url), pool_pre_ping=True)

    if engine.dialect.name == "postgresql":

        @event.listens_for(engine, "connect")
        def _set_read_only(dbapi_connection, _record):  # pragma: no cover - driver level
            dbapi_connection.read_only = True

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine


# --- rendering ----------------------------------------------------------------


def _one_line(value: str | None, width: int = 96) -> str:
    """Effect text on a single terminal line, for the human view only.

    Newlines become a visible marker rather than wrapping the report, and an
    over-long value is elided. This is display, never storage: the planner and
    the JSON output both carry Bandai's text verbatim.
    """
    if not value:
        return "<none>"
    flat = value.replace("\n", " / ")
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def render_human(plan: ImportPlan, digests: AssetDigests) -> None:
    counts = plan.counts()
    emit("== planned prints ==")
    emit(
        f"  {len(plan.prints)} official artwork(s): "
        + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    )
    coverage = plan.metadata_coverage()
    emit(
        "  official metadata published for: "
        + ", ".join(f"{k}={v}" for k, v in coverage.items())
    )
    statuses = plan.metadata_statuses()
    if statuses:
        emit(
            "  metadata vs existing prints: "
            + ", ".join(f"{k}={v}" for k, v in sorted(statuses.items()))
        )
    emit()
    for planned in plan.prints:
        emit(f"  {planned.entry_id}  [{planned.action}]")
        emit(
            f"     card      : {planned.card_code} {planned.official_card_name} "
            f"(lang={planned.language})"
        )
        emit(
            f"     product   : {planned.official_product_code or '<uncoded>'} "
            f"{planned.official_product_display_name or '<none>'}"
        )
        emit(
            f"     artwork   : variant={planned.official_asset_variant} "
            f"sha256={(planned.official_artwork_sha256 or '<none>')[:16]}"
        )
        emit(
            f"     treatment : {planned.treatment if planned.treatment is not None else 'NULL'}"
        )
        # What Bandai publishes for this exact occurrence. Truncated for the
        # human view only; the JSON output carries the value verbatim.
        emit(
            f"     official  : rarity={planned.official_rarity or '<none>'} "
            f"block={planned.official_block_icon or '<none>'} "
            f"name={planned.official_name or '<none>'}"
        )
        emit(f"     effect    : {_one_line(planned.official_effect_text)}")
        if planned.metadata_comparison is not None:
            emit(f"     metadata  : {planned.metadata_comparison.status}")
            for name, state in planned.metadata_comparison.fields.items():
                emit(f"       . {name}: {state}")
        emit(
            f"     existing  : canonical_card={planned.existing_canonical_card_id} "
            f"release_product={planned.existing_release_product_id} "
            f"card_print={planned.existing_card_print_id}"
        )
        emit(
            f"     plan      : outcome={planned.outcome} "
            f"verification={planned.verification_status} "
            f"creations={list(planned.creations) or '[]'}"
        )
        if planned.flags:
            emit(f"     flags     : {', '.join(planned.flags)}")
        for reason in planned.reasons:
            emit(f"       - {reason}")
        emit()

    if plan.mappings:
        emit("== lineage-less source mappings (read-only classification) ==")
        buckets: dict[str, list] = {}
        for mapping in plan.mappings:
            buckets.setdefault(mapping.classification, []).append(mapping)
        for classification in ("exact_candidate", "probable", "ambiguous", "unrelated"):
            rows = buckets.get(classification, [])
            emit(f"  {classification}: {len(rows)}")
            for mapping in rows if classification != "unrelated" else []:
                emit(
                    f"     #{mapping.mapping_id} {mapping.source_name} "
                    f"{mapping.legacy_card_code} ({mapping.review_status}) - {mapping.reason}"
                )
        emit()

    if digests.enabled:
        emit(f"assets fetched: {digests.fetched}, failures: {len(digests.failures)}")
        for failure in digests.failures:
            emit(f"  ! {failure}")
    else:
        emit("assets: not fetched (--no-fetch-assets)")
    emit()
    emit("NO DATABASE ROWS WERE WRITTEN - this command has no write path.")


def render_json(plan: ImportPlan, digests: AssetDigests) -> str:
    return json.dumps(
        {
            "source_catalogue": SOURCE_CATALOGUE,
            "counts": plan.counts(),
            "prints": [planned.to_dict() for planned in plan.prints],
            "lineage_less_mappings": [asdict(mapping) for mapping in plan.mappings],
            "assets": {
                "fetched": digests.fetched,
                "enabled": digests.enabled,
                "failures": digests.failures,
            },
            "writes_performed": 0,
        },
        ensure_ascii=False,
        indent=2,
    )


# --- entry point ---------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--card-code", help="Plan every official artwork of one card code.")
    target.add_argument("--series", help="Plan one Bandai series/product id, e.g. 550101.")
    parser.add_argument(
        "--staging",
        action="store_true",
        help="Plan against canonical staging, via a fresh verified read-only tunnel.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the plan as JSON.")
    parser.add_argument(
        "--no-fetch-assets",
        dest="fetch_assets",
        action="store_false",
        help="Do not fetch official assets to establish SHA-256 evidence.",
    )
    parser.add_argument(
        "--no-mappings",
        dest="classify_mappings",
        action="store_false",
        help="Skip the read-only lineage-less source mapping classification.",
    )
    parser.set_defaults(fetch_assets=True, classify_mappings=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        page = (
            fetch_card_code_page(args.card_code)
            if args.card_code
            else fetch_series_page(args.series)
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: could not read the official Card List: {exc}", file=sys.stderr)
        return EXIT_FAILED

    entries = page.entries
    if args.card_code:
        entries = page.entries_for_card(args.card_code)
    if not entries:
        print("FAIL: the official Card List returned no entries for that target.", file=sys.stderr)
        return EXIT_FAILED

    # The series index is only present on a series page; a freewords page
    # carries the same picker, so product titles resolve either way.
    series_index = page.series_index

    digests = AssetDigests(enabled=args.fetch_assets)

    engine = None
    if args.staging:
        try:
            url = verified_staging_url()
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: {exc}", file=sys.stderr)
            return EXIT_FAILED
        factory, engine = read_only_sessionmaker(url)
        session_context: Session = factory()
    else:
        from app.db import SessionLocal

        session_context = SessionLocal()

    try:
        if not args.staging and session_context.bind is not None:
            if session_context.bind.dialect.name == "postgresql":
                session_context.execute(text("SET TRANSACTION READ ONLY"))
        plan = plan_entries(
            session_context,
            entries,
            series_index=series_index,
            source_catalogue=SOURCE_CATALOGUE,
            digest_provider=digests,
            classify_mappings=args.classify_mappings,
        )
    finally:
        session_context.rollback()
        session_context.close()
        if engine is not None:
            engine.dispose()
        for process in _KEEP_ALIVE:
            process.terminate()
        _KEEP_ALIVE.clear()

    if args.json:
        emit(render_json(plan, digests))
    else:
        render_human(plan, digests)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
