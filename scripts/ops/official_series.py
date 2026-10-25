"""official-series-index: Bandai's Japanese Card List series picker against the catalogue.

Phase 0 of the catalogue-gap request (owner 2026-10-25). One polite request to the official JP
Card List (app.collect_official_cardlist_snapshot's fetcher: honest User-Agent, shared rate
limit, stops on 401/403/429/451) reads every series Bandai publishes, coded and uncoded
(promotion, premium collections, campaigns). Each is compared with the catalogue's release
products (read-only session): imported or not, and active prints per imported series. No
catalogue write, no price-source request.
"""
from __future__ import annotations

from pathlib import Path

from ops import common

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


def run(out_dir, fetch=None, products=None):
    from app.collect_official_cardlist_snapshot import RateLimitedFetcher, discover_series

    if fetch is None:
        found = discover_series(RateLimitedFetcher())
        series = [{"series_id": s.series_id, "code": s.official_code, "name": s.display_name} for s in found]
    else:
        series = fetch()
    if products is None:
        from ops import db as ops_db

        with ops_db.connection() as conn:
            products = [dict(r) for r in conn.execute(PRODUCTS_SQL).fetchall()]
            conn.rollback()
    rows, orphans = compare(series, products)
    missing = [r for r in rows if not r["in_catalogue"]]
    result = {"read_only": True, "source_requests": 1 if fetch is None else 0, "database_writes": 0,
              "bandai_series": len(rows), "in_catalogue": len(rows) - len(missing), "missing": len(missing),
              "catalogue_products_not_in_index": len(orphans), "series": rows, "orphans": orphans}
    common.write_json(Path(out_dir) / "official-series-index.json", result)
    return {k: result[k] for k in ("bandai_series", "in_catalogue", "missing", "catalogue_products_not_in_index")} | {
        "missing_series": [[r["series_id"], r["code"], r["name"]] for r in missing],
        "held": [[r["series_id"], r["code"], r["prints"]] for r in rows if r["in_catalogue"]],
        "orphans": [[o["series_id"], o["code"], o["name"], o["prints"]] for o in orphans]}
