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

Since the class-name fix (#223, live 2026-10-27 07:04Z) the canary refresh still refuses
(`artwork_not_confirmed_match:placeholder_image_url;no_raw_condition_price_available`), so each
page is also run through the collector's own current parser (snkrdunk_collector.extractor,
offline, the exact code the collectors run): the main image and its diagnostics, the condition
chip picker and raw/PSA10 results, a step-by-step trace of the retained-gallery recovery
(retained_gallery.primary_gallery_url) naming the step where it stops, the price-related class
tokens, and short excerpts around the first price chip and the gallery props.

Prices (owner 2026-10-27): on every refused page all 16 condition chips read 出品待ち, where the
captures before the change had real prices, so the prices now most likely arrive after the page
loads. `prices` reports where they live: price-like keys and yen amounts in the embedded Flight
data, excerpts around the condition labels in that data, API-looking paths the page names,
loading/skeleton markers inside and around the chip picker, and each chip's label and text.
"""
from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re

from ops import common

COLLECTOR = Path(__file__).resolve().parents[2] / "services" / "snkrdunk_collector"

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


def _collector_on_path():
    import sys

    if str(COLLECTOR) not in sys.path:
        sys.path.insert(0, str(COLLECTOR))


def _excerpt(text, needle, width=300):
    at = text.find(needle)
    if at < 0:
        return ""
    return re.sub(r"\s+", " ", text[max(0, at - width // 3): at + width])[:width]


def gallery_trace(soup):
    """retained_gallery.primary_gallery_url step by step: where it stops and what it saw."""
    import json
    from urllib.parse import urlsplit

    trace = {"stopped_at": None}
    chunks, bad_json = [], 0
    for script in soup.find_all("script"):
        body = script.string or ""
        match = re.fullmatch(r"\s*self\.__next_f\.push\((\[.*\])\)\s*;?\s*", body, re.S)
        if not match:
            continue
        try:
            value = json.loads(match.group(1))
        except (ValueError, TypeError):
            bad_json += 1
            continue
        if isinstance(value, list) and len(value) == 2 and value[0] == 1 and isinstance(value[1], str):
            chunks.append(value[1])
    payload = "".join(chunks)
    records = payload.splitlines()
    trace.update(push_chunks=len(chunks), push_chunks_not_json=bad_json, payload_bytes=len(payload.encode()),
                 records=len(records))
    if bad_json:
        trace["stopped_at"] = "a __next_f.push chunk is not JSON (the parser returns None)"
    keys, duplicates, gallery_modules, other_modules, elements = set(), 0, [], [], []
    # The export name may be inline (until 2026-10-26) or a reference to its own string
    # record: `8d:"ApparelGalleryContainer"` then `8e:I[213805,[...],"$8d"]`.
    strings, modules = {}, []
    for line in records:
        key, sep, encoded = line.partition(":")
        if not sep or not re.fullmatch(r"[0-9a-f]+", key):
            continue
        module = encoded.startswith("I")
        try:
            value = json.loads(encoded[1:] if module else encoded)
        except (ValueError, TypeError):
            continue
        if key in keys:
            duplicates += 1
        keys.add(key)
        if isinstance(value, str) and not module:
            strings[key] = value
        if module and isinstance(value, list) and value:
            modules.append((key, value[-1]))
        elif isinstance(value, list) and len(value) == 4 and value[0] == "$" and isinstance(value[1], str) \
                and isinstance(value[3], dict):
            elements.append(value)
    referenced = 0
    for key, last in modules:
        name = last if isinstance(last, str) else repr(last)[:60]
        if isinstance(last, str) and re.fullmatch(r"\$[0-9a-f]+", last) and last[1:] in strings:
            name, referenced = strings[last[1:]], referenced + 1
        if name == "ApparelGalleryContainer":
            gallery_modules.append("$L" + key)
        elif re.search("gallery|image|carousel", str(name), re.I):
            other_modules.append(str(name)[:60])
    trace["module_names_by_reference"] = referenced
    trace.update(duplicate_keys=duplicates, gallery_modules=gallery_modules,
                 other_image_modules=sorted(set(other_modules))[:8])
    if duplicates and not trace["stopped_at"]:
        trace["stopped_at"] = "a repeated Flight record key (the parser returns None)"
    galleries = [v[3] for v in elements if v[1] in set(gallery_modules)]
    trace["gallery_elements"] = len(galleries)
    if len(galleries) != 1:
        trace["stopped_at"] = trace["stopped_at"] or f"expected exactly one gallery element, found {len(galleries)}"
        return trace
    gallery = galleries[0]
    trace["gallery_props_excerpt"] = json.dumps(gallery, ensure_ascii=False)[:400]
    images, variants = gallery.get("mainImages"), gallery.get("variantSources")
    for label, value in (("main_images_ref", images), ("variant_sources_ref", variants)):
        if isinstance(value, str) and value.startswith("$"):
            trace[label] = {"ref": value[:40], "row": strings.get(value[1:].split(":")[0], "")[:200]}
    trace.update(gallery_prop_keys=sorted(gallery)[:20],
                 main_images=len(images) if isinstance(images, list) else type(images).__name__,
                 variant_sources=len(variants) if isinstance(variants, list) else type(variants).__name__)
    first = images[0] if isinstance(images, list) and images and isinstance(images[0], dict) else {}
    src = first.get("src")
    if isinstance(src, str):
        parts = urlsplit(src)
        trace["main_image_src_shape"] = {"scheme": parts.scheme, "host": parts.netloc,
                                         "path": re.sub(r"[A-Za-z0-9_-]{12,}", "<id>", parts.path)[:80],
                                         "query": bool(parts.query)}
    else:
        trace["main_image_first_keys"] = sorted(first)[:10]
    if not trace["stopped_at"]:
        _collector_on_path()
        from snkrdunk_collector.retained_gallery import primary_gallery_url

        trace["recovered"] = primary_gallery_url(soup) is not None
        if not trace["recovered"]:
            trace["stopped_at"] = "mainImages/variantSources shape or URL checks (see shape above)"
    return trace


PRICE_KEYS = re.compile(r'\\?"([A-Za-z]*(?:[Pp]rice|[Ll]isting|[Cc]ondition|[Ss]tock|[Ii]tems?Count)[A-Za-z]*)\\?"\s*:')
API_PATHS = re.compile(r'(?:https://[a-z.]*snkrdunk\.com)?/(?:v\d+|api)/[A-Za-z0-9_/{}$-]{3,80}')
LOADING = re.compile("skeleton|loading|placeholder|shimmer|spinner", re.I)


def _flight_payload(soup):
    import json

    chunks = []
    for script in soup.find_all("script"):
        match = re.fullmatch(r"\s*self\.__next_f\.push\((\[.*\])\)\s*;?\s*", script.string or "", re.S)
        if not match:
            continue
        try:
            value = json.loads(match.group(1))
        except (ValueError, TypeError):
            continue
        if isinstance(value, list) and len(value) == 2 and isinstance(value[1], str):
            chunks.append(value[1])
    return "".join(chunks)


def price_trace(soup, text):
    """Where the condition prices live on this page, and whether the chip picker is still loading."""
    payload = _flight_payload(soup)
    keys = Counter(PRICE_KEYS.findall(payload))
    yen = re.findall(r"[¥￥]\s?[0-9][0-9,]{2,}", payload)
    labels = [m.start() for m in re.finditer(r'\\?"(?:PSA10|A)\\?"', payload)][:2]
    excerpts = [re.sub(r"\s+", " ", payload[max(0, at - 120): at + 260]) for at in labels]
    paths = sorted({p for p in API_PATHS.findall(text) if re.search("price|size|condition|listing|product|apparel", p, re.I)})
    chips, loading_in, loading_near = [], Counter(), Counter()
    _collector_on_path()
    from snkrdunk_collector import extractor as ex

    container, _ = ex.find_condition_chip_container(soup)
    if container is not None:
        for chip in container.find_all("button", recursive=False):
            chips.append(" | ".join(p.get_text(" ", strip=True) for p in chip.find_all("p", recursive=False))[:40])
        for tag in container.find_all(True):
            for token in tag.get("class") or []:
                if LOADING.search(token):
                    loading_in[token] += 1
            if tag.get("aria-busy") == "true":
                loading_in["aria-busy"] += 1
        parent = container
        for _ in range(4):
            parent = parent.parent if parent is not None else None
            if parent is None:
                break
            for token in parent.get("class") or []:
                if LOADING.search(token):
                    loading_near[token] += 1
    page_loading = Counter(t for tag in soup.find_all(True) for t in (tag.get("class") or []) if LOADING.search(t))
    return {
        "payload_price_keys": keys.most_common(15), "payload_yen_amounts": len(yen), "payload_yen_sample": yen[:6],
        "payload_label_excerpts": [e[:380] for e in excerpts],
        "api_paths": paths[:12],
        "chips": chips[:16], "chip_loading_markers": loading_in.most_common(6),
        "around_chips_loading_markers": loading_near.most_common(6),
        "page_loading_markers": page_loading.most_common(8),
    }


def parse_trace(text):
    """The collectors' current parser on this page, offline."""
    _collector_on_path()
    from bs4 import BeautifulSoup
    from snkrdunk_collector import extractor as ex

    soup = BeautifulSoup(text, "html.parser")
    image, image_diag = ex.find_main_product_image(soup)
    container, chip_diag = ex.find_condition_chip_container(soup)
    raw = ex.extract_raw_conditions(soup)
    psa10 = ex.extract_psa10(soup)
    price_tokens = Counter()
    for tag in soup.find_all(True):
        for token in tag.get("class") or []:
            if re.search("chip|variant|price|awaiting|condition|picker|size", token, re.I):
                price_tokens[f"{tag.name}.{token}"] += 1
    chip_at = "出品待ち" if "出品待ち" in text else "¥"
    return {
        "image": (image or "")[-90:], "image_diagnostics": image_diag,
        "chip_container": container is not None, "chip_diagnostics": chip_diag,
        "raw_floor_jpy": raw.get("raw_floor_jpy"), "raw_conditions": sorted((raw.get("conditions") or {}).keys()),
        "psa10": psa10.get("outcome"),
        "price_class_tokens": price_tokens.most_common(12),
        "gallery": gallery_trace(soup),
        "chip_excerpt": _excerpt(text, chip_at),
        "gallery_excerpt": _excerpt(text, "ApparelGalleryContainer"),
        "prices": price_trace(soup, text),
    }


def inspect(conn, rows, label):
    out = []
    for r in rows:
        item = {"kind": label, "attempt_id": r["attempt_id"], "snapshot_id": r["raw_snapshot_id"],
                "finished_at": r["finished_at"]}
        try:
            snap, text = load_text(conn, r["raw_snapshot_id"])
            item.update(http_status=snap["http_status"], parser_version=snap["parser_version"], **describe(text))
            try:
                item["parser"] = parse_trace(text)
            except Exception as exc:  # noqa: BLE001 - reported per page
                item["parser"] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
        except Exception as exc:  # noqa: BLE001 - a page that cannot be decoded is reported, not fatal
            item["error"] = type(exc).__name__
        out.append(item)
    return out


def run(out_dir, refused=2, captured=1):
    from ops import db as ops_db

    with ops_db.connection(statement_timeout_ms=120000) as conn:
        pages = inspect(conn, conn.execute(REFUSED_SQL, (CHANGE_AT, refused)).fetchall(), "refused") + \
            inspect(conn, conn.execute(CAPTURED_SQL, (CHANGE_AT, captured)).fetchall(), "captured_before")
        conn.rollback()
    result = {"read_only": True, "source_requests": 0, "database_writes": 0, "pages": pages}
    common.write_json(Path(out_dir) / "snkr-page-check.json", result)
    return result
