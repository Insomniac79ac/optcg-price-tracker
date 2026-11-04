"""snkr-refused-photos: the exact SNKRDUNK photo behind each quarantined artwork refusal (read-only).

Owner 2026-11-04 (plan B, "build plan B"). The collector refuses a capture when the listing photo
fails its average-hash test against the mapped print's official image; for mapping 4456 the hashes
were average 24 (limit 12), dhash 9, phash 14, and the owner identified 4456, 4423 and 4356 as the
right parallels. An owner confirmation the collector honours is bound to the exact photo it
confirmed, so this reads, for every blocked SNKRDUNK refresh item refused by the artwork check, the
page the collector stored at that refusal (raw_snapshots, decoded offline like snkr-page-check) and
runs the collector's own find_main_product_image on it: that URL is the photo the check compared.

Per item: work id, mapping id, mapped print, listing, the refusal's attempt and time, and the photo
URL. No SNKRDUNK request, no write.
"""
from __future__ import annotations

from pathlib import Path

from ops import common

OUTPUT = "snkr-refused-photos.json"
MAX_ITEMS = 200

ITEMS_SQL = """
select w.id work_id, m.id mapping_id, m.card_print_id, m.canonical_source_listing_identity listing,
  (select a.id from freshness_attempts a where a.work_id = w.id and a.outcome = 'identity_refusal'
     and a.raw_snapshot_id is not null order by a.id desc limit 1) attempt_id
from freshness_work w
join sources s on s.id = w.source_id and s.name = 'snkrdunk'
join source_card_mappings m on m.id = w.source_card_mapping_id
where w.kind = 'refresh' and w.state = 'blocked'
  and w.last_failure like 'artwork_not_confirmed_match%%'
order by m.id
limit %s"""
ATTEMPT_SQL = "select raw_snapshot_id, finished_at from freshness_attempts where id = %s"


def photo_url(text):
    """The collector's own main-image reading of a stored page (offline)."""
    from ops.snkr_page_check import _collector_on_path

    _collector_on_path()
    from bs4 import BeautifulSoup
    from snkrdunk_collector import extractor

    url, _ = extractor.find_main_product_image(BeautifulSoup(text, "html.parser"))
    return url


def run(out_dir):
    from ops import db as ops_db
    from ops.snkr_page_check import load_text

    rows, problems = [], []
    with ops_db.connection(statement_timeout_ms=120000) as conn:
        items = conn.execute(ITEMS_SQL, (MAX_ITEMS + 1,)).fetchall()
        if len(items) > MAX_ITEMS:
            raise common.Refused(f"more than {MAX_ITEMS} blocked artwork refusals; narrow before reading")
        for item in items:
            row = {k: item[k] for k in ("work_id", "mapping_id", "card_print_id", "listing", "attempt_id")}
            try:
                attempt = conn.execute(ATTEMPT_SQL, (item["attempt_id"],)).fetchone() if item["attempt_id"] else None
                if attempt is None:
                    raise ValueError("no retained refusal page")
                _, text = load_text(conn, attempt["raw_snapshot_id"])
                row["refused_at"] = attempt["finished_at"].isoformat() if attempt["finished_at"] else None
                row["photo_url"] = photo_url(text)
            except Exception as exc:  # noqa: BLE001 - one unreadable page is reported, not fatal
                row["photo_url"] = None
                row["error"] = f"{type(exc).__name__}: {exc}"[:120]
                problems.append(item["mapping_id"])
            rows.append(row)
        conn.rollback()
    summary = {"items": len(rows), "without_photo": problems, "source_requests": 0, "database_writes": 0,
               "rows": [[r["mapping_id"], r["card_print_id"], r["listing"], r["work_id"], r.get("refused_at"),
                         r["photo_url"]] for r in rows]}
    common.write_json(Path(out_dir) / OUTPUT, {**summary, "detail": rows})
    return summary
