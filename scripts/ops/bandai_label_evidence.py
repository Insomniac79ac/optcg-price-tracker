"""bandai-label-evidence: fresh Bandai evidence for SNKRDUNK product labels (read-only).

Owner 2026-11-03 (perfectionist, fix 3). The 37 SNKRDUNK listings discovery found from the seeds
carry no set code: the label tables (release_product_aliases.py, source_product_aliases.py) know
only OP-01 to OP-04 and EB-01, and their evidence standard re-derives every row from a frozen
Bandai catalogue that is not in the repository (gitignored, operator machine) and whose Asia-EN
half is gone (catalogue_import.py). This runbook captures the evidence the standard asks for,
fresh, from Bandai itself:

1. Both series pickers: Bandai's Japanese Card List and Asia-EN Card List (one request each).
2. For every coded series in TARGET_PREFIXES, its JP and Asia-EN series pages (card-code
   membership), at one request per 2 s through app.collect_official_cardlist_snapshot's fetcher
   (honest User-Agent, stops on 401/403/429/451). About 50 requests.
3. The SNKRDUNK labels stored on candidates (the title's trailing "(...)" group, read-only
   session), each tested against check 1 and check 2 of the standard: its normalised whole label
   equals a published series title (with or without the bracketed code) and that title names
   exactly one product code across both catalogues. Check 3 per code: JP and Asia-EN membership
   identical.

It writes nothing and decides nothing: the label rows are added by a reviewed PR, from these facts.
No price-source request.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ops import common

COLLECTOR = Path(__file__).resolve().parents[2] / "services" / "snkrdunk_collector"
JP_CARD_LIST = "https://www.onepiece-cardgame.com/cardlist/"
ASIA_EN_CARD_LIST = "https://asia-en.onepiece-cardgame.com/cardlist/"
SERIES_ID = re.compile(r"\d{6}")
LATIN_CODE = re.compile(r"\[([^\]]+)\]\s*$")
BRACKETS = re.compile(r"[\[【].*?[\]】]")
TARGET_PREFIXES = ("OP", "EB", "PRB")
MAX_SERIES_PAGES = 60
OUTPUT = "bandai-label-evidence.json"

LABELS_SQL = """
select c.title, c.detected_set_code set_code, c.detected_card_code code
from snkrdunk_candidates c where c.title is not null
"""


def series_code(name):
    """The bracketed code, verbatim: JP '…【OP-08】' through the catalogue's own parser, Asia-EN
    '… [OP-08]' the same way with square brackets; None when uncoded."""
    from app.services.official_cardlist import product_code_from_display_name

    code = product_code_from_display_name(name)
    if code is None:
        m = LATIN_CODE.search((name or "").strip())
        code = m.group(1).strip() if m else None
    return code


def compact(codes):
    """Sorted card codes as prefix runs: 'OP08:001-118 OP05:060' (membership, reviewable)."""
    runs, by_prefix = [], {}
    for code in sorted(codes):
        prefix, _, number = code.rpartition("-")
        if number.isdigit():
            by_prefix.setdefault(prefix, []).append(int(number))
        else:
            runs.append(code)
    for prefix in sorted(by_prefix):
        nums, start, prev = by_prefix[prefix], None, None
        parts = []
        for n in nums + [None]:
            if start is None:
                start = prev = n
            elif n is not None and n == prev + 1:
                prev = n
            else:
                parts.append(f"{start:03d}" if start == prev else f"{start:03d}-{prev:03d}")
                start = prev = n
        runs.append(f"{prefix}:{','.join(parts)}")
    return " ".join(runs)


def digest(codes):
    return hashlib.sha256("\n".join(sorted(codes)).encode()).hexdigest()[:12]


def title_index(series_by_catalogue, normalise):
    """Normalised published title -> codes carrying it, across both catalogues, indexed with
    and without the bracketed code (the form a storefront writes), as the alias tests do."""
    index = {}
    for rows in series_by_catalogue.values():
        for s in rows:
            for form in (s["name"], BRACKETS.sub("", s["name"])):
                key = normalise(form)
                if key:
                    index.setdefault(key, set()).add(s["code"])
    return index


def label_verdicts(titles, index, normalise, product_re):
    """Per distinct stored label: listings, check 1 + 2 verdict and the code it names."""
    labels = {}
    for row in titles:
        m = product_re.search(row["title"] or "")
        if not m:
            continue
        label = m.group(1).strip()
        entry = labels.setdefault(label, {"listings": 0, "set_codes": set()})
        entry["listings"] += 1
        entry["set_codes"].add(row["set_code"])
    out = []
    for label, entry in sorted(labels.items(), key=lambda kv: -kv[1]["listings"]):
        key = normalise(label)
        codes = index.get(key, set())
        verdict = ("official_unique" if len(codes) == 1 and None not in codes
                   else "official_ambiguous" if codes else "no_published_title")
        out.append({"label": label, "key": key, "listings": entry["listings"],
                    "stored_set_codes": sorted(str(c) for c in entry["set_codes"]),
                    "verdict": verdict, "codes": sorted(str(c) for c in codes)})
    return out


def run(out_dir, fetcher=None, read_titles=None, read_index=None, read_codes=None):
    """read_index(catalogue) -> [(series_id, display_name)] and read_codes(catalogue, series_id)
    -> card codes replace the live Bandai reads (tests); read_titles replaces the DB read."""
    import sys

    if str(COLLECTOR) not in sys.path:
        sys.path.insert(0, str(COLLECTOR))
    from snkrdunk_collector.discovery_evidence.release_product_aliases import normalise_label
    from snkrdunk_collector.discovery_evidence.snkrdunk_listing_evidence import _PRODUCT_RE

    catalogues = {"bandai_jp": JP_CARD_LIST, "bandai_asia_en": ASIA_EN_CARD_LIST}
    if read_index is None or read_codes is None:
        from app.collect_official_cardlist_snapshot import RateLimitedFetcher
        from app.services.official_cardlist import parse_card_list

        fetcher = fetcher or RateLimitedFetcher(min_interval=2.0)

        def page(catalogue, series_id=None):
            base = catalogues[catalogue]
            url = base if series_id is None else f"{base}?series={series_id}"
            status, body, _ = fetcher.get(url)
            if status != 200:
                raise common.Refused(f"Bandai {url}: HTTP {status}")
            return parse_card_list(body.decode("utf-8", "replace"), series_id or "")

        read_index = read_index or (lambda c: [(s.series_id, s.display_name) for s in page(c).series_index])
        read_codes = read_codes or (lambda c, sid: {e.card_code for e in page(c, sid).entries if e.card_code})

    from app.collect_official_cardlist_snapshot import CollectionStopped

    series, members = {}, {}
    try:
        for name in catalogues:
            series[name] = [{"series_id": sid, "name": title, "code": series_code(title)}
                            for sid, title in read_index(name) if SERIES_ID.fullmatch(sid)]
        targets = [(name, s) for name, rows in series.items() for s in rows
                   if s["code"] and s["code"].split("-")[0] in TARGET_PREFIXES]
        if len(targets) > MAX_SERIES_PAGES:
            raise common.Refused(f"{len(targets)} coded series pages exceed {MAX_SERIES_PAGES}; not reading blind")
        for name, s in targets:
            codes = set(read_codes(name, s["series_id"]))
            if not codes:
                raise common.Refused(f"{name} series {s['series_id']} lists no card codes")
            members[(name, s["series_id"])] = codes
    except CollectionStopped as exc:
        raise common.Refused(f"Bandai refused collection: {exc}") from None

    by_code = {}
    for name, s in [(n, s) for n, rows in series.items() for s in rows if s["code"]]:
        by_code.setdefault(s["code"], {}).setdefault(name, []).append(s)
    rows = []
    for code in sorted(by_code):
        if code.split("-")[0] not in TARGET_PREFIXES:
            continue
        jp, en = by_code[code].get("bandai_jp", []), by_code[code].get("bandai_asia_en", [])
        jp_codes = members.get(("bandai_jp", jp[0]["series_id"])) if len(jp) == 1 else None
        en_codes = members.get(("bandai_asia_en", en[0]["series_id"])) if len(en) == 1 else None
        rows.append({"code": code, "jp": [s["series_id"] for s in jp], "en": [s["series_id"] for s in en],
                     "en_title": en[0]["name"] if len(en) == 1 else None,
                     "jp_n": len(jp_codes or ()), "en_n": len(en_codes or ()),
                     "same_membership": bool(jp_codes) and jp_codes == en_codes,
                     "jp_only": compact(jp_codes - en_codes) if jp_codes and en_codes else None,
                     "en_only": compact(en_codes - jp_codes) if jp_codes and en_codes else None,
                     "jp_digest": digest(jp_codes) if jp_codes else None,
                     "jp_members": compact(jp_codes) if jp_codes else None})

    index = title_index(series, normalise_label)
    if read_titles is None:
        from ops import db as ops_db

        with ops_db.connection() as conn:
            titles = [dict(r) for r in conn.execute(LABELS_SQL).fetchall()]
            conn.rollback()
    else:
        titles = read_titles()
    labels = label_verdicts(titles, index, normalise_label, _PRODUCT_RE)

    result = {"read_only": True, "database_writes": 0, "price_source_requests": 0,
              "bandai_requests": getattr(fetcher, "requests", None),
              "series_in_pickers": {k: len(v) for k, v in series.items()},
              "labels": labels, "codes": rows,
              "pickers": {k: [[s["series_id"], s["code"], s["name"]] for s in v] for k, v in series.items()}}
    common.write_json(Path(out_dir) / OUTPUT, result)
    # Annotation budget: labels first (the decision input), then per-code facts; pickers last.
    return {"bandai_requests": result["bandai_requests"], "series_in_pickers": result["series_in_pickers"],
            "labels": [[x["label"], x["listings"], x["verdict"], x["codes"], x["stored_set_codes"]] for x in labels],
            "codes": [[r["code"], r["jp"], r["en"], r["en_title"], r["jp_n"], r["en_n"], r["same_membership"],
                       r["jp_only"], r["en_only"], r["jp_digest"], r["jp_members"]] for r in rows],
            # Every series title in both pickers, so check 2 (uniqueness) can be re-derived from a
            # committed copy of this summary (owner 2026-11-03).
            "pickers": {k: [[s["series_id"], s["name"]] for s in v] for k, v in series.items()}}
