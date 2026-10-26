"""snkr-page-check: what SNKRDUNK's stored product pages show where the collector expects the main image.

Since 2026-10-26 08:29Z SNKRDUNK refreshes fail closed with
`main_image_not_found:expected_exactly_one_mainImage_img` (snkrdunk_collector.extractor
find_main_product_image wants exactly one <img> whose class ends in `__mainImage`). This reads
the pages the collector already stored - no SNKRDUNK request - for the newest refusals of that
kind and the newest successful captures before the change, decodes them (dictionary-encoded RAW,
opcg_source_identity.raw_payload, base chains followed), and reports per page: HTTP status, size,
the number of <img> whose class ends in `__mainImage`, every class token that mentions an image
(top 15), whether the retained gallery props (`ApparelGalleryContainer`) are present, and a short
escaped excerpt around the first `mainImage`. Read-only session; no source request.
"""
from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re

from ops import common

REFUSED_SQL = """
select a.id attempt_id, a.raw_snapshot_id, a.finished_at
from freshness_attempts a join freshness_work w on w.id = a.work_id join sources s on s.id = w.source_id
where s.name = 'snkrdunk' and w.kind = 'refresh' and a.outcome = 'identity_refusal'
  and a.raw_snapshot_id is not null and a.finished_at >= %s
order by a.id desc limit %s"""
CAPTURED_SQL = """
select a.id attempt_id, a.raw_snapshot_id, a.finished_at
from freshness_attempts a join freshness_work w on w.id = a.work_id join sources s on s.id = w.source_id
where s.name = 'snkrdunk' and w.kind = 'refresh' and a.outcome = 'captured'
  and a.raw_snapshot_id is not null and a.finished_at < %s
order by a.id desc limit %s"""
SNAPSHOT_SQL = """
select r.id, r.raw_content, r.content_hash, r.http_status, r.fetched_at, r.parser_version, d.base_snapshot_id
from raw_snapshots r left join raw_snapshot_dictionaries d on d.id = r.id where r.id = %s"""
CHANGE_AT = "2026-10-26T08:00:00+00:00"
MAX_DEPTH = 4


class _Images(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images, self.tokens = 0, Counter()
        self.main = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        for token in classes:
            if re.search("image|img|gallery|photo|thumb", token, re.I):
                self.tokens[f"{tag}.{token}"] += 1
        if tag == "img":
            self.images += 1
            if any(c.endswith("__mainImage") for c in classes):
                src = attrs.get("src") or ""
                self.main.append(re.sub(r"\?.*$", "", src)[-80:])


def load_text(conn, snapshot_id, depth=0):
    """The snapshot's plaintext, following dictionary bases (bounded)."""
    from opcg_source_identity.raw_payload import PREFIX, decode

    if depth > MAX_DEPTH:
        raise ValueError("base chain too deep")
    row = conn.execute(SNAPSHOT_SQL, (snapshot_id,)).fetchone()
    if row is None:
        raise ValueError("snapshot not found")
    stored = row["raw_content"] or ""
    if not stored.startswith(PREFIX):
        return row, stored
    data = decode(stored, expected_hash=row["content_hash"],
                  load_base=lambda base_id: load_text(conn, base_id, depth + 1)[1].encode("utf-8"))
    return row, data.decode("utf-8") if isinstance(data, bytes) else data


def describe(text):
    parser = _Images()
    parser.feed(text)
    at = text.find("mainImage")
    excerpt = text[max(0, at - 160): at + 200] if at >= 0 else ""
    excerpt = re.sub(r"\s+", " ", excerpt)
    return {"bytes": len(text.encode("utf-8")), "img_tags": parser.images,
            "main_image_imgs": len(parser.main), "main_image_srcs": parser.main[:3],
            "mainImage_mentions": text.count("mainImage"),
            "gallery_props": "ApparelGalleryContainer" in text,
            "image_class_tokens": parser.tokens.most_common(15), "excerpt": excerpt[:360]}


def inspect(conn, rows, label):
    out = []
    for r in rows:
        item = {"kind": label, "attempt_id": r["attempt_id"], "snapshot_id": r["raw_snapshot_id"],
                "finished_at": r["finished_at"]}
        try:
            snap, text = load_text(conn, r["raw_snapshot_id"])
            item.update(http_status=snap["http_status"], parser_version=snap["parser_version"], **describe(text))
        except Exception as exc:  # noqa: BLE001 - a page that cannot be decoded is reported, not fatal
            item["error"] = type(exc).__name__
        out.append(item)
    return out


def run(out_dir, refused=5, captured=3):
    from ops import db as ops_db

    with ops_db.connection(statement_timeout_ms=120000) as conn:
        pages = inspect(conn, conn.execute(REFUSED_SQL, (CHANGE_AT, refused)).fetchall(), "refused") + \
            inspect(conn, conn.execute(CAPTURED_SQL, (CHANGE_AT, captured)).fetchall(), "captured_before")
        conn.rollback()
    result = {"read_only": True, "source_requests": 0, "database_writes": 0, "pages": pages}
    common.write_json(Path(out_dir) / "snkr-page-check.json", result)
    return result
