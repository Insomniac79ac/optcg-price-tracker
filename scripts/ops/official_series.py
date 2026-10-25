"""official-series-index: Bandai's Japanese Card List series picker against the catalogue.

Phase 0 of the catalogue-gap request (owner 2026-10-25). Polite requests (one, plus at most eight
series pages for the uncoded and missing series, 2 s apart) to the official JP
Card List (app.collect_official_cardlist_snapshot's fetcher: honest User-Agent, shared rate
limit, stops on 401/403/429/451) reads every series Bandai publishes, coded and uncoded
(promotion, premium collections, campaigns). Each is compared with the catalogue's release
products (read-only session): imported or not, and active prints per imported series. No
catalogue write, no price-source request.
"""
from __future__ import annotations

from pathlib import Path

from ops import common

# The page carries other numeric <option> lists (cost and power filters); a Bandai series id
# is six digits (for example 550101). Anything else is not a series.
SERIES_ID = __import__("re").compile(r"\d{6}")
# Uncoded groupings that hold many products (promotion cards, limited products) and series
# missing from the catalogue are broken down by the product each entry names (入手情報).
MAX_BREAKDOWN_PAGES = 8

PRODUCTS_SQL = """
select rp.source_series_id series_id, rp.official_code code, rp.display_name name,
  count(p.id) filter (where p.is_active) prints
from release_products rp left join card_prints p on p.release_product_id = rp.id
where rp.source_catalogue = 'bandai_jp'
group by rp.id order by rp.source_series_id
"""


def compare(series, products):
    """Rows per Bandai series (in_catalogue, prints) and catalogue products absent from the index."""
    by_id = {}
    for row in products:
        by_id.setdefault(row["series_id"], []).append(row)
    rows = []
    for s in series:
        held = by_id.get(s["series_id"], [])
        rows.append({"series_id": s["series_id"], "code": s["code"], "name": s["name"],
                     "in_catalogue": bool(held), "prints": sum(r["prints"] for r in held)})
    listed = {s["series_id"] for s in series}
    orphans = [r for r in products if r["series_id"] not in listed]
    return rows, orphans


def breakdown(series_rows, products, read_page):
    """Per product named on the selected series pages: Bandai entries vs catalogue prints."""
    held = {}
    for row in products:
        held[(row["series_id"], row["name"])] = held.get((row["series_id"], row["name"]), 0) + row["prints"]
    out = []
    for s in series_rows:
        counts = {}
        for entry in read_page(s["series_id"]):
            # Bandai's link labels (カードリスト, 商品情報) are dropped by the parser
            # (official_cardlist.OBTAIN_INFO_LINK_LABELS).
            names = list(entry.product_names) or ["(no product named)"]
            for name in names:
                counts[name] = counts.get(name, 0) + 1
        for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            out.append({"series_id": s["series_id"], "product": name, "bandai_entries": n,
                        "catalogue_prints": held.get((s["series_id"], name), 0)})
    return out


def run(out_dir, fetch=None, products=None, read_page=None):
    from app.collect_official_cardlist_snapshot import RateLimitedFetcher, discover_series
    from app.services.official_cardlist import card_list_url, parse_card_list

    fetcher = None
    if fetch is None:
        fetcher = RateLimitedFetcher(min_interval=2.0)
        found = discover_series(fetcher)
        series = [{"series_id": s.series_id, "code": s.official_code, "name": s.display_name} for s in found]
    else:
        series = fetch()
    series = [s for s in series if SERIES_ID.fullmatch(s["series_id"])]
    if products is None:
        from ops import db as ops_db

        with ops_db.connection() as conn:
            products = [dict(r) for r in conn.execute(PRODUCTS_SQL).fetchall()]
            conn.rollback()
    rows, orphans = compare(series, products)
    missing = [r for r in rows if not r["in_catalogue"]]
    selected = [r for r in rows if not r["code"] or not r["in_catalogue"]][:MAX_BREAKDOWN_PAGES]
    if read_page is None and fetcher is not None:
        def read_page(series_id):
            status, body, _ = fetcher.get(card_list_url(series_id))
            if status != 200:
                raise common.Refused(f"Bandai series {series_id}: HTTP {status}")
            return parse_card_list(body.decode("utf-8", "replace"), series_id).entries
    products_by_page = breakdown(selected, products, read_page) if read_page else []
    result = {"read_only": True, "source_requests": (1 + len(selected)) if fetcher else 0, "database_writes": 0,
              "bandai_series": len(rows), "in_catalogue": len(rows) - len(missing), "missing": len(missing),
              "catalogue_products_not_in_index": len(orphans), "series": rows, "orphans": orphans,
              "breakdown": products_by_page}
    common.write_json(Path(out_dir) / "official-series-index.json", result)
    # Annotations carry at most ~27,000 characters: counts and the breakdown go first, the long
    # held list last and compact, so a truncation loses the least useful part.
    return {k: result[k] for k in ("bandai_series", "in_catalogue", "missing", "catalogue_products_not_in_index")} | {
        "missing_series": [[r["series_id"], r["code"], r["name"]] for r in missing],
        "orphans": [[o["series_id"], o["code"], o["name"], o["prints"]] for o in orphans],
        "breakdown": [[b["series_id"], b["product"], b["bandai_entries"], b["catalogue_prints"]]
                      for b in products_by_page],
        "held": [f'{r["code"] or r["series_id"]}:{r["prints"]}' for r in rows if r["in_catalogue"]]}
