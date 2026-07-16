import argparse
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from worker.adapters.snkrdunk_discovery import (
    SnkrdunkCandidateData,
    SnkrdunkDiscoveryAdapter,
    SnkrdunkDiscoveryError,
    is_blocked_response,
)
from worker.app_logging import log_exception, record_app_log
from worker.db import SessionLocal
from worker.matching.candidate_store import apply_match, get_snkrdunk_source, upsert_candidate
from worker.models import Card, RawSnapshot, SnkrdunkDiscoveryRun
from worker.path_utils import find_project_root
from worker.settings import settings

logger = logging.getLogger(__name__)

DEFAULT_SEED_FILE_RELATIVE = Path("data/source_seeds/snkrdunk_one_piece_urls.txt")


@dataclass
class DiscoveryRunSummary:
    """Plain snapshot of a SnkrdunkDiscoveryRun, safe to read after the run's
    transaction has been committed or rolled back (e.g. --dry-run)."""

    id: int | None
    status: str
    pages_fetched: int
    candidates_found: int
    candidates_matched: int
    candidates_needing_review: int
    error_message: str | None


def _default_seed_file() -> Path:
    """Resolved lazily (never at import time) so pytest collection and one-off
    script execution never depend on a particular on-disk repo layout."""
    configured = settings.SNKRDUNK_SEED_FILE
    if configured:
        configured_path = Path(configured)
        if configured_path.is_absolute():
            return configured_path
        return find_project_root() / configured_path

    return find_project_root() / DEFAULT_SEED_FILE_RELATIVE


def _read_seed_urls(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"seed file not found: {path}")

    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def discover_snkrdunk(
    db: Session,
    max_pages: int = 5,
    limit_candidates: int | None = None,
    auto_match_threshold: float | None = None,
    dry_run: bool = False,
    seed_file: Path | None = None,
    adapter: SnkrdunkDiscoveryAdapter | None = None,
) -> DiscoveryRunSummary:
    seed_file = seed_file or _default_seed_file()
    seed_urls = _read_seed_urls(seed_file)
    threshold = (
        auto_match_threshold
        if auto_match_threshold is not None
        else settings.SNKRDUNK_AUTO_MATCH_THRESHOLD
    )
    owns_adapter = adapter is None
    adapter = adapter or SnkrdunkDiscoveryAdapter()

    source = get_snkrdunk_source(db)
    cards = db.query(Card).all()

    run = SnkrdunkDiscoveryRun(seed_url=seed_urls[0] if seed_urls else "", status="running")
    db.add(run)
    db.flush()
    logger.info("Discovery run %s started with %d seed url(s).", run.id, len(seed_urls))

    pages_fetched = 0
    blocked_pages = 0
    candidates_found = 0
    candidates_matched = 0
    candidates_needing_review = 0
    visited_urls: set[str] = set()
    limit_reached = False

    try:
        for seed_url in seed_urls:
            if limit_reached or pages_fetched >= max_pages:
                break

            url: str | None = seed_url
            while url and pages_fetched < max_pages:
                if url in visited_urls:
                    logger.info("Already visited %s in this run, stopping this chain.", url)
                    break
                visited_urls.add(url)

                try:
                    snapshot = adapter.fetch_page(url)
                except (SnkrdunkDiscoveryError, Exception):
                    logger.exception("Failed to fetch discovery page %s, skipping.", url)
                    break

                raw_snapshot = RawSnapshot(
                    source_id=source.id,
                    source_url=snapshot.source_url,
                    fetched_at=snapshot.fetched_at,
                    http_status=snapshot.http_status,
                    content_hash=snapshot.content_hash,
                    raw_content=snapshot.raw_content,
                    parser_version=snapshot.parser_version,
                )
                db.add(raw_snapshot)
                db.flush()
                pages_fetched += 1
                logger.info("Page fetched: %s (status=%s).", url, snapshot.http_status)

                if is_blocked_response(snapshot.http_status):
                    blocked_pages += 1
                    logger.warning(
                        "SNKRDUNK blocked or refused automated access for %s with status %s. "
                        "Stored raw snapshot and skipped parsing.",
                        url,
                        snapshot.http_status,
                    )
                    break

                try:
                    page_result = adapter.parse_search_page(snapshot)
                except Exception:
                    logger.exception("Failed to parse discovery page %s, skipping.", url)
                    break

                logger.info("Candidates parsed: %d from %s.", len(page_result.candidates), url)

                for parsed in page_result.candidates:
                    if limit_candidates is not None and candidates_found >= limit_candidates:
                        limit_reached = True
                        break

                    try:
                        candidate, _is_new = upsert_candidate(db, run.id, parsed)
                    except Exception:
                        logger.exception("Failed to store candidate %s, skipping.", parsed.source_url)
                        continue

                    candidates_found += 1

                    if candidate.match_status != "pending":
                        continue

                    status = apply_match(db, source, candidate, cards, threshold)
                    if status == "auto_matched":
                        candidates_matched += 1
                        logger.info(
                            "Candidate matched: %s -> card_id=%s (confidence=%.2f).",
                            candidate.source_url,
                            candidate.matched_card_id,
                            candidate.match_confidence,
                        )
                    elif status == "needs_review":
                        candidates_needing_review += 1
                        logger.info(
                            "Candidate needs review: %s (matched_card_id=%s, confidence=%s).",
                            candidate.source_url,
                            candidate.matched_card_id,
                            candidate.match_confidence,
                        )

                if limit_reached:
                    logger.info("Reached --limit-candidates=%s, stopping discovery.", limit_candidates)
                    break

                url = page_result.next_page_url
                if url:
                    logger.info("Following pagination link: %s", url)

            if limit_reached:
                break

        if pages_fetched >= max_pages:
            logger.info("Reached --max-pages=%s, stopping discovery.", max_pages)

        if pages_fetched > 0 and blocked_pages == pages_fetched:
            run.status = "blocked"
        elif blocked_pages > 0:
            run.status = "completed_with_warnings"
        else:
            run.status = "completed"
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        logger.exception("Discovery run %s failed.", run.id)
        log_exception(
            "worker",
            "scraping",
            f"SNKRDUNK discovery run {run.id} failed.",
            exc,
            related_run_id=run.id,
            related_entity_type="snkrdunk_discovery_run",
            related_entity_id=run.id,
        )
    finally:
        run.finished_at = datetime.now(timezone.utc)
        run.pages_fetched = pages_fetched
        run.candidates_found = candidates_found
        run.candidates_matched = candidates_matched
        if owns_adapter:
            adapter.close()

    logger.info(
        "Discovery run finished: id=%s status=%s pages_fetched=%d blocked_pages=%d "
        "candidates_found=%d candidates_matched=%d candidates_needing_review=%d",
        run.id,
        run.status,
        pages_fetched,
        blocked_pages,
        candidates_found,
        candidates_matched,
        candidates_needing_review,
    )

    if run.status == "blocked":
        record_app_log(
            "warning",
            "worker",
            "scraping",
            f"SNKRDUNK discovery run {run.id} was fully blocked "
            f"({blocked_pages}/{pages_fetched} page(s)). Manual import may be needed.",
            context={"pages_fetched": pages_fetched, "blocked_pages": blocked_pages},
            related_run_id=run.id,
            related_entity_type="snkrdunk_discovery_run",
            related_entity_id=run.id,
        )
    elif run.status == "completed_with_warnings":
        record_app_log(
            "warning",
            "worker",
            "scraping",
            f"SNKRDUNK discovery run {run.id} completed with {blocked_pages} blocked page(s).",
            context={"pages_fetched": pages_fetched, "blocked_pages": blocked_pages},
            related_run_id=run.id,
            related_entity_type="snkrdunk_discovery_run",
            related_entity_id=run.id,
        )

    # Snapshot before commit/rollback: after a rollback (--dry-run), the ORM
    # object's row never existed, so touching its attributes afterward would
    # raise ObjectDeletedError.
    summary = DiscoveryRunSummary(
        id=run.id,
        status=run.status,
        pages_fetched=run.pages_fetched,
        candidates_found=run.candidates_found,
        candidates_matched=run.candidates_matched,
        candidates_needing_review=candidates_needing_review,
        error_message=run.error_message,
    )

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Discover SNKRDUNK One Piece Card Game listings and match them to canonical cards."
    )
    parser.add_argument("--max-pages", type=int, default=5, help="Max pages to fetch this run.")
    parser.add_argument("--limit-candidates", type=int, default=None, help="Max candidates to process this run.")
    parser.add_argument(
        "--auto-match-threshold", type=float, default=None,
        help="Minimum confidence required to auto-match (defaults to SNKRDUNK_AUTO_MATCH_THRESHOLD).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Run discovery without committing to the database.")
    parser.add_argument("--seed-file", type=Path, default=None, help="Override the seed URL file path.")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = build_arg_parser().parse_args()

    if settings.SCRAPING_MODE != "live":
        print(
            f"SCRAPING_MODE is '{settings.SCRAPING_MODE}', not 'live'; "
            "SNKRDUNK discovery only runs in live mode."
        )
        return

    db = SessionLocal()
    try:
        run = discover_snkrdunk(
            db,
            max_pages=args.max_pages,
            limit_candidates=args.limit_candidates,
            auto_match_threshold=args.auto_match_threshold,
            dry_run=args.dry_run,
            seed_file=args.seed_file,
        )
        print(
            f"Discovery run {run.id}: status={run.status} pages_fetched={run.pages_fetched} "
            f"candidates_found={run.candidates_found} candidates_matched={run.candidates_matched}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
