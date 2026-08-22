"""CLI: collect a raw evidence snapshot of the Japanese official Card List.

    python -m app.collect_official_cardlist_snapshot --pages-only
    python -m app.collect_official_cardlist_snapshot --fetch-images --resume
    python -m app.collect_official_cardlist_snapshot --analyze
    python -m app.collect_official_cardlist_snapshot --analyze --atlas-coverage --staging

This collects evidence and analyses it. It has no canonical write mode: no
CanonicalCard, ReleaseProduct, CardPrint, SourceCardMapping or pricing row is
created or modified by any flag, and the only database access is a read-only
staging session used by --atlas-coverage.

Politeness
----------
One shared rate limiter across a small thread pool, so concurrency never
multiplies the request rate. Retries use exponential backoff and give up
rather than hammering. Pages and images already present in the snapshot are
reused, so --resume re-fetches nothing it already has. There is no anti-bot
handling of any kind: on a 403/429 the run stops and reports the boundary
(see STOP_STATUSES).

Exit codes
----------
    0  the requested work completed
    1  collection stopped at a boundary, or a fatal error
    2  usage error
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.official_cardlist import (
    OfficialSeries,
    card_list_url,
    has_real_pagination,
    parse_card_list,
)
from app.services.official_snapshot import (
    ANALYSIS_DIR,
    ASSETS_FILE,
    CONTENT_TYPE_EXTENSIONS,
    ENTRIES_FILE,
    SERIES_FILE,
    SNAPSHOT_VERSION,
    SOURCE_CATALOGUE,
    Snapshot,
    asset_url_parts,
    entry_record,
    occurrence_matrix,
    series_record,
    suffix_family_analysis,
    suffix_inventory,
    variance_report,
)

EXIT_OK = 0
EXIT_STOPPED = 1
EXIT_USAGE = 2

USER_AGENT = (
    "CardPirateAtlas-official-cardlist-snapshot/1.0 "
    "(+evidence collection for card catalogue reconciliation)"
)
DEFAULT_OUTPUT = Path("data/official_snapshots/bandai_jp/current")
DEFAULT_WORKERS = 4
DEFAULT_MIN_INTERVAL = 0.2  # seconds between request starts, across all workers
DEFAULT_RETRIES = 3
TIMEOUT_SECONDS = 60.0

# Statuses that mean "the site is telling us to stop". We stop and report
# rather than rotating agents, adding proxies or slowing into a grey area.
STOP_STATUSES = (401, 403, 429, 451)


def emit(line: str = "") -> None:
    print(line, flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CollectionStopped(RuntimeError):
    """The site refused us. Reported, never worked around."""


class RateLimitedFetcher:
    """Shared-rate, retrying, caching HTTP reader."""

    def __init__(
        self,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        retries: int = DEFAULT_RETRIES,
        user_agent: str = USER_AGENT,
    ) -> None:
        self.min_interval = min_interval
        self.retries = retries
        self.user_agent = user_agent
        self._lock = threading.Lock()
        self._next_allowed = 0.0
        self.requests = 0
        self.retried = 0

    def _wait_turn(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_allowed)
            self._next_allowed = start + self.min_interval
        delay = start - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    def get(self, url: str) -> tuple[int, bytes, str | None]:
        """(status, body, content_type). Raises CollectionStopped on refusal."""
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait_turn()
            request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                    self.requests += 1
                    return (
                        response.status,
                        response.read(),
                        response.headers.get("Content-Type"),
                    )
            except urllib.error.HTTPError as exc:
                if exc.code in STOP_STATUSES:
                    raise CollectionStopped(
                        f"HTTP {exc.code} from {url} - the site is refusing collection. "
                        "Stopping rather than escalating scraping technique."
                    ) from exc
                last_error = exc
                if exc.code < 500 and exc.code != 408:
                    return exc.code, b"", None
            except Exception as exc:  # noqa: BLE001 - network flake
                last_error = exc
            if attempt < self.retries:
                self.retried += 1
                time.sleep((2**attempt) * 0.5 + random.uniform(0, 0.3))
        raise RuntimeError(f"{url}: giving up after {self.retries + 1} attempts: {last_error}")


# --- collection --------------------------------------------------------------


def discover_series(fetcher: RateLimitedFetcher) -> list[OfficialSeries]:
    """Every catalogue grouping, from the Card List's own series picker.

    Nothing is hardcoded: the list is whatever Bandai currently publishes,
    including the uncoded promotional/limited groupings.
    """
    status, body, _ = fetcher.get(card_list_url("550101"))
    if status != 200:
        raise RuntimeError(f"series discovery failed: HTTP {status}")
    page = parse_card_list(body.decode("utf-8", "replace"), "550101")
    return list(page.series_index)


def collect_pages(
    snapshot: Snapshot,
    series_list: list[OfficialSeries],
    fetcher: RateLimitedFetcher,
    *,
    resume: bool,
    workers: int,
) -> dict[str, Any]:
    """Fetch and store every series page, then parse them into records."""
    failures: list[dict[str, Any]] = []
    paginated: list[str] = []
    fetched_at = now_iso()

    def fetch_one(series: OfficialSeries) -> None:
        if resume and snapshot.has_page(series.series_id):
            return
        url = card_list_url(series.series_id)
        try:
            status, body, _ = fetcher.get(url)
        except CollectionStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            failures.append({"series_id": series.series_id, "url": url, "error": str(exc)})
            return
        if status != 200:
            failures.append({"series_id": series.series_id, "url": url, "status": status})
            return
        snapshot.write_page(series.series_id, body.decode("utf-8", "replace"))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(fetch_one, series_list))

    series_rows: list[dict[str, Any]] = []
    entry_rows: list[dict[str, Any]] = []
    for series in series_list:
        html = snapshot.read_page(series.series_id)
        if html is None:
            continue
        if has_real_pagination(html):
            # The crawler refuses to silently keep only the first page.
            paginated.append(series.series_id)
        page = parse_card_list(html, series.series_id)
        for entry in page.entries:
            entry_rows.append(
                entry_record(
                    entry,
                    series_id=series.series_id,
                    series_url=series.source_url,
                    product_title=series.display_name,
                    product_code=series.official_code,
                    fetched_at=fetched_at,
                )
            )
        series_rows.append(
            series_record(series, fetched_at=fetched_at, entry_count=len(page.entries))
        )

    snapshot.save(SERIES_FILE, series_rows)
    snapshot.save(ENTRIES_FILE, entry_rows)
    return {
        "series": len(series_rows),
        "entries": len(entry_rows),
        "page_failures": failures,
        "series_with_real_pagination": paginated,
    }


def collect_images(
    snapshot: Snapshot, fetcher: RateLimitedFetcher, *, resume: bool, workers: int
) -> dict[str, Any]:
    """Fetch every distinct asset URL, storing bytes by content digest."""
    entries = snapshot.load(ENTRIES_FILE)
    urls = sorted({row["image_url"] for row in entries if row.get("image_url")})

    known: dict[str, dict[str, Any]] = {}
    if resume:
        known = {row["url"]: row for row in snapshot.load(ASSETS_FILE) if row.get("sha256")}

    results: dict[str, dict[str, Any]] = dict(known)
    failures: list[dict[str, Any]] = []
    lock = threading.Lock()

    def fetch_one(url: str) -> None:
        if url in results:
            return
        record = asset_url_parts(url)
        record["fetched_at"] = now_iso()
        try:
            status, body, content_type = fetcher.get(url)
        except CollectionStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            with lock:
                failures.append({"url": url, "error": str(exc)})
            return
        record["http_status"] = status
        record["content_type"] = (content_type or "").split(";")[0].strip() or None
        if status != 200 or not body:
            with lock:
                failures.append({"url": url, "status": status})
                results[url] = record
            return
        extension = CONTENT_TYPE_EXTENSIONS.get(record["content_type"] or "", ".bin")
        digest, path = snapshot.write_image(body, extension)
        record["sha256"] = digest
        record["byte_length"] = len(body)
        record["stored_path"] = str(path.relative_to(snapshot.root))
        record.update(_dimensions(body))
        with lock:
            results[url] = record

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(fetch_one, urls))

    rows = [results[u] for u in sorted(results)]
    snapshot.save(ASSETS_FILE, rows)
    digests = {r.get("sha256") for r in rows if r.get("sha256")}
    return {
        "asset_urls": len(urls),
        "asset_records": len(rows),
        "distinct_digests": len(digests),
        "asset_failures": failures,
    }


def _dimensions(payload: bytes) -> dict[str, Any]:
    """Width/height when they can be read without re-encoding anything."""
    try:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(payload)) as image:
            return {"width": image.width, "height": image.height, "image_format": image.format}
    except Exception:  # noqa: BLE001 - dimensions are optional evidence
        return {"width": None, "height": None, "image_format": None}


# --- analysis ------------------------------------------------------------------


def run_analysis(snapshot: Snapshot) -> dict[str, Any]:
    entries = snapshot.load(ENTRIES_FILE)
    assets = {row["url"]: row for row in snapshot.load(ASSETS_FILE)}

    inventory = suffix_inventory(entries)
    matrix = occurrence_matrix(entries, assets)
    variance = variance_report(matrix)
    suffixes = suffix_family_analysis(matrix)

    snapshot.save_analysis("suffix_inventory.json", inventory)
    snapshot.save_analysis("variance_report.json", variance)
    snapshot.save_analysis("suffix_family_analysis.json", suffixes)
    from app.services.official_snapshot import write_jsonl

    write_jsonl(snapshot.analysis_dir / "occurrence_matrix.jsonl", matrix)

    return {
        "entries": len(entries),
        "card_codes": len(matrix),
        "distinct_asset_urls": len({e["image_url"] for e in entries if e.get("image_url")}),
        "distinct_digests": len({a.get("sha256") for a in assets.values() if a.get("sha256")}),
        "suffix_families": inventory["families"],
        "variance": variance,
        "suffix_analysis": suffixes,
    }


def run_atlas_coverage(snapshot: Snapshot, *, staging: bool) -> dict[str, Any]:
    """Compare the official dataset with Atlas. Read-only, no writes."""
    from sqlalchemy import select

    from app.models import CanonicalCard, CardPrint, ReleaseProduct
    from app.services.official_asset_variant import parse_official_asset_variant

    if staging:
        from app.plan_canonical_print_import import (
            read_only_sessionmaker,
            verified_staging_url,
        )

        factory, engine = read_only_sessionmaker(verified_staging_url())
        session = factory()
    else:
        from app.db import SessionLocal

        session, engine = SessionLocal(), None

    try:
        entries = snapshot.load(ENTRIES_FILE)
        assets = {row["url"]: row for row in snapshot.load(ASSETS_FILE)}

        official_codes = {e["card_code"] for e in entries if e.get("card_code")}
        # Official identity: (card_code, product_code, variant) - the shape the
        # live exact-print key resolves to once ids are assigned.
        official_identities: dict[tuple, dict] = {}
        for row in entries:
            variant = parse_official_asset_variant(row.get("image_url"), row.get("card_code"))
            key = (row["card_code"], row.get("product_code"), variant)
            official_identities.setdefault(key, row)

        atlas_rows = session.execute(
            select(CardPrint, CanonicalCard, ReleaseProduct)
            .join(CanonicalCard, CanonicalCard.id == CardPrint.canonical_card_id)
            .outerjoin(ReleaseProduct, ReleaseProduct.id == CardPrint.release_product_id)
        ).all()
        atlas_codes = {c.card_code for _, c, _ in atlas_rows}

        represented, unmatched, digest_mismatch, metadata_differences = [], [], [], []
        for print_row, card, product in atlas_rows:
            key = (
                card.card_code,
                product.official_code if product else None,
                print_row.official_asset_variant,
            )
            official = official_identities.get(key)
            if official is None:
                unmatched.append(
                    {"card_print_id": print_row.id, "card_code": card.card_code,
                     "product_code": product.official_code if product else None,
                     "variant": print_row.official_asset_variant}
                )
                continue
            represented.append(key)
            digest = (assets.get(official.get("image_url") or "") or {}).get("sha256")
            if digest and print_row.artwork_key and digest != print_row.artwork_key:
                digest_mismatch.append(
                    {"card_print_id": print_row.id, "card_code": card.card_code,
                     "atlas_artwork_key": print_row.artwork_key, "official_sha256": digest}
                )
            for atlas_value, official_value, name in (
                (card.name_jp, official.get("card_name"), "name_jp"),
                (card.rarity, official.get("rarity"), "rarity"),
            ):
                if atlas_value and official_value and atlas_value.strip() != official_value.strip():
                    metadata_differences.append(
                        {"card_print_id": print_row.id, "card_code": card.card_code,
                         "field": name, "atlas": atlas_value, "official": official_value}
                    )

        missing_identities = [
            {"card_code": k[0], "product_code": k[1], "variant": k[2],
             "entry_id": v.get("entry_id")}
            for k, v in official_identities.items()
            if k not in set(represented)
        ]
        cards_missing_occurrences = sorted(
            {m["card_code"] for m in missing_identities if m["card_code"] in atlas_codes}
        )

        return {
            "official_occurrences": len(entries),
            "official_distinct_identities": len(official_identities),
            "atlas_prints": len(atlas_rows),
            "atlas_identities_represented": len(set(represented)),
            "missing_canonical_card_codes": sorted(official_codes - atlas_codes),
            "missing_canonical_card_codes_count": len(official_codes - atlas_codes),
            "existing_cards_missing_occurrences": cards_missing_occurrences,
            "missing_official_identities_count": len(missing_identities),
            "missing_official_identities_sample": missing_identities[:40],
            "atlas_prints_without_official_evidence": unmatched,
            "image_digest_mismatches": digest_mismatch,
            "metadata_differences": metadata_differences,
        }
    finally:
        session.rollback()
        session.close()
        if engine is not None:
            engine.dispose()
        if staging:
            from app.plan_canonical_print_import import _KEEP_ALIVE

            for process in _KEEP_ALIVE:
                process.terminate()
            _KEEP_ALIVE.clear()


# --- entry point -----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalogue", default=SOURCE_CATALOGUE, choices=[SOURCE_CATALOGUE])
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Snapshot directory.")
    parser.add_argument("--resume", action="store_true", help="Reuse pages/assets already stored.")
    parser.add_argument("--pages-only", action="store_true", help="Collect pages, not images.")
    parser.add_argument("--fetch-images", action="store_true", help="Collect the card images.")
    parser.add_argument("--analyze", action="store_true", help="Run the analyses over a snapshot.")
    parser.add_argument(
        "--atlas-coverage", action="store_true", help="Compare the snapshot with Atlas (read-only)."
    )
    parser.add_argument("--staging", action="store_true", help="Use verified read-only staging.")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--min-interval", type=float, default=DEFAULT_MIN_INTERVAL)
    parser.add_argument("--limit-series", type=int, default=None, help="Collect only the first N.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    snapshot = Snapshot(Path(args.output))
    fetcher = RateLimitedFetcher(min_interval=args.min_interval)

    # The manifest describes the snapshot directory, not this invocation, so
    # it is always loaded and merged. --resume controls what gets re-fetched;
    # running --analyze later must not erase what --fetch-images recorded.
    manifest = snapshot.load_manifest()
    manifest.setdefault("snapshot_version", SNAPSHOT_VERSION)
    manifest.setdefault("source_catalogue", args.catalogue)
    manifest["started_at"] = now_iso()

    collecting = args.pages_only or args.fetch_images
    try:
        if collecting:
            emit("== discovering catalogue groupings ==")
            series_list = discover_series(fetcher)
            if args.limit_series:
                series_list = series_list[: args.limit_series]
            emit(f"  {len(series_list)} series/products published by the catalogue")
            manifest["series_discovered"] = len(series_list)

            emit("== collecting pages ==")
            page_result = collect_pages(
                snapshot, series_list, fetcher, resume=args.resume, workers=args.workers
            )
            manifest["pages"] = page_result
            emit(f"  {page_result['series']} series, {page_result['entries']} entry occurrences")
            if page_result["series_with_real_pagination"]:
                emit(
                    "  !! server-side pagination detected on: "
                    f"{page_result['series_with_real_pagination']} - collection is INCOMPLETE"
                )
            if page_result["page_failures"]:
                emit(f"  !! {len(page_result['page_failures'])} page failure(s)")

        if args.fetch_images:
            emit("== collecting images ==")
            image_result = collect_images(
                snapshot, fetcher, resume=args.resume, workers=args.workers
            )
            manifest["images"] = image_result
            emit(
                f"  {image_result['asset_urls']} distinct URLs -> "
                f"{image_result['distinct_digests']} distinct digests"
            )
            if image_result["asset_failures"]:
                emit(f"  !! {len(image_result['asset_failures'])} asset failure(s)")

        if args.analyze:
            emit("== analysing ==")
            manifest["analysis"] = run_analysis(snapshot)
            emit(f"  suffix families: {manifest['analysis']['suffix_families']}")

        if args.atlas_coverage:
            emit("== Atlas coverage (read-only) ==")
            manifest["atlas_coverage"] = run_atlas_coverage(snapshot, staging=args.staging)
            emit(
                "  missing canonical card codes: "
                f"{manifest['atlas_coverage']['missing_canonical_card_codes_count']}"
            )

    except CollectionStopped as exc:
        emit()
        emit(f"STOPPED: {exc}")
        manifest["stopped"] = str(exc)
        manifest["finished_at"] = now_iso()
        snapshot.save_manifest(manifest)
        return EXIT_STOPPED

    manifest["finished_at"] = now_iso()
    manifest["requests"] = {"issued": fetcher.requests, "retried": fetcher.retried}
    manifest["disk_usage"] = snapshot.disk_usage()
    snapshot.save_manifest(manifest)

    emit()
    emit(f"snapshot: {snapshot.root}")
    emit(f"  {json.dumps(manifest['disk_usage'])}")
    emit("NO CANONICAL ROWS WERE WRITTEN - this command has no canonical write path.")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
