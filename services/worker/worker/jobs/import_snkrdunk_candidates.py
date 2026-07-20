import argparse
import csv
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from worker.adapters.snkrdunk_discovery import SnkrdunkCandidateData
from worker.app_logging import record_app_log
from worker.db import SessionLocal
from worker.matching.candidate_store import apply_match, get_snkrdunk_source, upsert_candidate
from worker.models import Card, SnkrdunkDiscoveryRun
from worker.settings import settings

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ("source_url",)


@dataclass
class ImportSummary:
    candidates_imported: int = 0
    candidates_updated: int = 0
    candidates_auto_matched: int = 0
    candidates_needing_review: int = 0
    skipped_rows: int = 0
    skipped_reasons: list[str] = field(default_factory=list)

    def print_report(self) -> None:
        print(f"candidates_imported: {self.candidates_imported}")
        print(f"candidates_updated: {self.candidates_updated}")
        print(f"candidates_auto_matched: {self.candidates_auto_matched}")
        print(f"candidates_needing_review: {self.candidates_needing_review}")
        print(f"skipped_rows: {self.skipped_rows}")


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _parse_int(value: str | None) -> int | None:
    value = _clean(value)
    if value is None:
        return None
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else None


def _row_to_candidate_data(row: dict[str, str]) -> SnkrdunkCandidateData | None:
    source_url = _clean(row.get("source_url"))
    if not source_url:
        return None

    return SnkrdunkCandidateData(
        source_url=source_url,
        title=_clean(row.get("title")),
        price_jpy=_parse_int(row.get("price_jpy")),
        image_url=_clean(row.get("image_url")),
        listing_count=_parse_int(row.get("listing_count")),
        condition_label=_clean(row.get("condition_label")),
        raw_text=_clean(row.get("raw_text")) or "",
    )


def import_snkrdunk_candidates(
    csv_path: str | Path,
    db: Session | None = None,
    auto_match_threshold: float | None = None,
) -> ImportSummary:
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    threshold = (
        auto_match_threshold
        if auto_match_threshold is not None
        else settings.SNKRDUNK_AUTO_MATCH_THRESHOLD
    )

    summary = ImportSummary()
    owns_session = db is None
    if db is None:
        db = SessionLocal()

    try:
        source = get_snkrdunk_source(db)
        cards = db.query(Card).all()

        run = SnkrdunkDiscoveryRun(seed_url=str(csv_path), status="manual_import")
        db.add(run)
        db.flush()
        logger.info("Manual SNKRDUNK candidate import started: run=%s file=%s", run.id, csv_path)
        record_app_log(
            "info",
            "worker",
            "import",
            f"Manual SNKRDUNK candidate import started (run={run.id}, file={csv_path}) - "
            "likely due to live discovery being blocked.",
            context={"file": str(csv_path)},
            related_run_id=run.id,
            related_entity_type="snkrdunk_discovery_run",
            related_entity_id=run.id,
        )

        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                parsed = _row_to_candidate_data(row)
                if parsed is None:
                    summary.skipped_rows += 1
                    logger.warning("Skipping row with missing source_url: %r", row)
                    continue

                try:
                    candidate, is_new = upsert_candidate(db, run.id, parsed)
                except Exception:
                    logger.exception("Failed to store candidate %s, skipping.", parsed.source_url)
                    summary.skipped_rows += 1
                    continue

                if is_new:
                    summary.candidates_imported += 1
                    logger.info("Candidate imported: %s", candidate.source_url)
                else:
                    summary.candidates_updated += 1
                    logger.info("Candidate updated (deduplicated by source_url): %s", candidate.source_url)

                if candidate.match_status != "unmatched":
                    continue

                status = apply_match(db, source, candidate, cards, threshold)
                if status == "matched":
                    summary.candidates_auto_matched += 1
                    logger.info(
                        "Candidate matched: %s -> card_id=%s (confidence=%.2f).",
                        candidate.source_url,
                        candidate.matched_card_id,
                        candidate.match_confidence,
                    )
                elif status in ("suggested", "ambiguous"):
                    summary.candidates_needing_review += 1
                    logger.info(
                        "Candidate needs review: %s (matched_card_id=%s, confidence=%s).",
                        candidate.source_url,
                        candidate.matched_card_id,
                        candidate.match_confidence,
                    )

        run.finished_at = datetime.now(timezone.utc)
        run.candidates_found = summary.candidates_imported + summary.candidates_updated
        run.candidates_matched = summary.candidates_auto_matched

        logger.info(
            "Manual import finished: run=%s candidates_imported=%d candidates_updated=%d "
            "candidates_auto_matched=%d candidates_needing_review=%d skipped_rows=%d",
            run.id,
            summary.candidates_imported,
            summary.candidates_updated,
            summary.candidates_auto_matched,
            summary.candidates_needing_review,
            summary.skipped_rows,
        )

        db.commit()
    finally:
        if owns_session:
            db.close()

    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description="Manually import SNKRDUNK candidates from a CSV file (fallback for when "
        "live discovery is blocked). Does not scrape SNKRDUNK."
    )
    parser.add_argument("csv_path", help="Path to a snkrdunk_candidates CSV file.")
    parser.add_argument(
        "--auto-match-threshold", type=float, default=None,
        help="Minimum confidence required to auto-match (defaults to SNKRDUNK_AUTO_MATCH_THRESHOLD).",
    )
    args = parser.parse_args()

    summary = import_snkrdunk_candidates(args.csv_path, auto_match_threshold=args.auto_match_threshold)
    summary.print_report()


if __name__ == "__main__":
    main()
