"""catalogue-import: add Bandai JP catalogue prints to staging (owner-gated).

Phase 2 of the catalogue-gap request (owner 2026-10-26). The import engine already exists and is
not changed here: app.import_frozen_bandai_to_canonical_staging plans with
print_import_planner and writes only through CanonicalImportApplier, with every pin it carries
(snapshot identity, attested alembic revision, import lock, untouched price tables). It used to
need an operator machine holding the ~1 GB frozen snapshot and a `railway connect` SSH tunnel.
This runbook gives it both inside the ops-write workflow:

1. Snapshot. A fresh capture of Bandai's Japanese Card List into the run's own directory:
   every six-digit series page (the picker's cost and power filter options are not series and
   would inflate sibling counts), and images only for the entries the scope will plan. One
   shared rate limit of 1 request per second, two workers, the collector's honest User-Agent,
   stop on 401/403/429/451. Pages with server-side pagination or failed page reads refuse.
2. Scope. A named scope from docs/agent/CATALOGUE_IMPORT_SCOPES.json (reviewed by PR): coded
   series ids go to the importer's --series; uncoded product names are checked against
   app.services.uncoded_product_evidence and REPORTED with the rule each passes or fails. They
   are not imported yet: the standard's Asia-EN substitution has to be re-measured first (the
   frozen Asia-EN snapshot it relied on is gone, and asia-en pages label the block "Card
   Set(s)", which the JP parser never reads), and that is the owner's decision in step C.
3. Target. The importer's own verified_staging_target, with only open_tunnel rerouted
   (canonical_staging_target.ReroutedChecker around the real checker) to the pinned staging
   Postgres TCP proxy (ops/db.py: Railway project, environment and service ids, never a stored
   URL). Every fingerprint, the revision-equals-head check and the attestation are the
   established checker's; a wrong database that answers is refused.
4. Plan SHA-256. Over the scope, every whole planned print (identity, official metadata,
   proposed card and product, existing ids, flags) and the entry record it was planned from. Apply re-captures,
   re-plans and refuses inside the importer (before the applier runs, nothing written) unless
   the plan equals the dry run the owner reviewed.

Dry run (default): read-only session at the server, plan and the engine's dry-run report.
Apply: --apply with the dry run's plan_sha256, after the owner approves the run.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
from urllib.parse import quote

from ops import common

SCOPES_FILE = "docs/agent/CATALOGUE_IMPORT_SCOPES.json"
SERIES_ID = re.compile(r"\d{6}")
MIN_INTERVAL = 1.0
WORKERS = 2
ROW_LIMIT = 120


# --- scope ---------------------------------------------------------------------------------

def load_scopes(root=None):
    data = json.loads((Path(root or common.ROOT) / SCOPES_FILE).read_text(encoding="utf-8"))
    return data["scopes"]


def resolve_scope(name, scopes):
    """The named scope, validated; refuses an unknown name or a malformed entry.

    series            coded Bandai series ids, imported through the importer's --series
    uncoded_products  exact product names, reported against the uncoded evidence standard
    uncoded_series    uncoded catch-all series ids: every product their entries name is reported
    exclude_products  exact names left out of uncoded_series expansion
    asia_en_measure   also read Bandai's Asia-EN catalogue for its uncoded series (step C)
    """
    if not name:
        raise common.Refused("catalogue-import needs --scope (a name in " + SCOPES_FILE + ")")
    if name not in scopes:
        raise common.Refused(f"unknown scope {name!r}; known: {', '.join(sorted(scopes))}")
    scope = scopes[name]
    series = list(scope.get("series") or [])
    products = list(scope.get("uncoded_products") or [])
    uncoded_series = list(scope.get("uncoded_series") or [])
    excludes = list(scope.get("exclude_products") or [])
    if not all(isinstance(s, str) and SERIES_ID.fullmatch(s) for s in series + uncoded_series):
        raise common.Refused(f"scope {name!r}: series must be six-digit Bandai ids")
    if not all(isinstance(p, str) and p and p == p.strip() for p in products + excludes):
        raise common.Refused(f"scope {name!r}: product names must be exact, trimmed strings")
    if not series and not products and not uncoded_series:
        raise common.Refused(f"scope {name!r} names nothing to plan")
    return {"name": name, "series": series, "uncoded_products": products, "uncoded_series": uncoded_series,
            "exclude_products": excludes, "asia_en_measure": bool(scope.get("asia_en_measure"))}


def expand_products(entries, scope):
    """Uncoded product names the scope reports: the explicit ones, plus every name an entry of
    an uncoded_series carries, minus exclude_products. Sorted, exact strings."""
    names = set(scope.get("uncoded_products") or ())
    buckets, excludes = set(scope.get("uncoded_series") or ()), set(scope.get("exclude_products") or ())
    for row in entries:
        if row.get("source_series_id") in buckets:
            names.update(row.get("product_names") or ())
    return sorted(names - excludes)


def scoped_entry_ids(entries, scope, products=None):
    """Entry ids a scope plans: captured under one of its series, or naming one of its products."""
    series = set(scope["series"])
    products = set(scope.get("uncoded_products") or ()) if products is None else set(products)
    return frozenset(
        row["entry_id"] for row in entries
        if row.get("source_series_id") in series or products & set(row.get("product_names") or ()))


# --- snapshot ------------------------------------------------------------------------------

def capture(root, scope, fetcher=None):
    """A fresh JP snapshot at `root`: all series pages, images for the scope's entries only."""
    from app import collect_official_cardlist_snapshot as collector
    from app.services.official_snapshot import ENTRIES_FILE, SNAPSHOT_VERSION, SOURCE_CATALOGUE, Snapshot

    snapshot = Snapshot(Path(root))
    fetcher = fetcher or collector.RateLimitedFetcher(min_interval=MIN_INTERVAL)
    manifest = {"snapshot_version": SNAPSHOT_VERSION, "source_catalogue": SOURCE_CATALOGUE,
                "started_at": collector.now_iso(), "collected_by": "ops catalogue-import"}
    try:
        series = [s for s in collector.discover_series(fetcher) if SERIES_ID.fullmatch(s.series_id)]
        pages = collector.collect_pages(snapshot, series, fetcher, resume=False, workers=WORKERS)
        if pages["series_with_real_pagination"]:
            raise common.Refused("Bandai series with server-side pagination (capture incomplete): "
                                 + ", ".join(pages["series_with_real_pagination"]))
        if pages["page_failures"]:
            raise common.Refused(f"{len(pages['page_failures'])} Bandai series page(s) failed to load")
        known = {s.series_id for s in series}
        missing = [s for s in scope["series"] + scope.get("uncoded_series", []) if s not in known]
        if missing:
            raise common.Refused("scope series not on Bandai's list: " + ", ".join(missing))
        entries = snapshot.load(ENTRIES_FILE)
        products = expand_products(entries, scope)
        wanted = scoped_entry_ids(entries, scope, products)
        images = collector.collect_images(snapshot, fetcher, resume=False, workers=WORKERS,
                                          only_entry_ids=wanted)
    except collector.CollectionStopped as exc:
        raise common.Refused(f"Bandai refused collection: {exc}") from None
    manifest.update(finished_at=collector.now_iso(), pages=pages, images=images,
                    requests={"issued": fetcher.requests, "retried": fetcher.retried})
    snapshot.save_manifest(manifest)
    return {"series": pages["series"], "entries": pages["entries"], "scoped_entries": len(wanted),
            "asset_urls": images.get("asset_urls"), "asset_failures": len(images.get("asset_failures") or []),
            "requests": fetcher.requests, "products": products}


# --- uncoded products: reported, not imported ------------------------------------------------

NOT_EVALUATED = "Asia-EN substitution not evaluated (owner decision, Phase 2 step C)"


def uncoded_report(root, products, identity):
    """Per product: the evidence standard's verdict on the JP rules (with the proposed
    single-product catch-all exception allowed and flagged), and its member codes."""
    from app.services.uncoded_product_evidence import UncodedProductEvidenceError, prove_uncoded_product

    out = []
    for name in products:
        try:
            ev = prove_uncoded_product(name, jp_root=Path(root), asia_en_root=Path(root),
                                       snapshot_identity=identity, asia_en_absence_proof=NOT_EVALUATED,
                                       allow_single_product_catchall=True)
            out.append({"product": name, "jp_rules": "pass", "series": ev.source_series_id,
                        "members": len(ev.member_card_codes), "codes": list(ev.member_card_codes)[:80],
                        "single_product_catchall": ev.single_product_catchall})
        except UncodedProductEvidenceError as exc:
            out.append({"product": name, "jp_rules": "refused", "rule": exc.rule, "detail": exc.detail[:300]})
    return out


def compact_uncoded(rows):
    """Small enough for the annotations: passes with member counts, refusals grouped by rule."""
    passed = [[r["product"], r["members"]] + (["single_product_catchall"] if r.get("single_product_catchall") else [])
              for r in rows if r["jp_rules"] == "pass"]
    refused = {}
    for r in rows:
        if r["jp_rules"] != "pass":
            hint = ""
            for pattern in (r"\(e\.g\. '([^']*)'", r"card code '([^']*)'", r"for '([^']*)'", r"spans series (\[[^\]]*\])"):
                found = re.search(pattern, r["detail"])
                if found:
                    hint = found.group(1)
                    break
            refused.setdefault(r["rule"], []).append([r["product"], hint])
    return {"products": len(rows), "pass": passed, "refused": refused}


def multi_product_sets(entries, products, limit=25):
    """Which product names share one entry (rule 4's cases), most common first."""
    from collections import Counter

    wanted = set(products)
    counts = Counter(" + ".join(sorted(row["product_names"])) for row in entries
                     if len(row.get("product_names") or ()) > 1 and wanted & set(row["product_names"]))
    return [[names, n] for names, n in counts.most_common(limit)]


ASIA_EN_CARD_LIST = "https://asia-en.onepiece-cardgame.com/cardlist/"
ASIA_EN_CODED = re.compile(r"\[[A-Z]{2,4}-?\d{1,3}\]\s*$")
ASIA_EN_MAX_PAGES = 6


def asia_en_measure(fetcher, limit=30):
    """Does Bandai's Asia-EN catalogue name products for its uncoded series' cards?

    Reads the series picker and at most six uncoded series pages (same fetcher, same rate
    limit). Its obtain block is labelled in English ('Card Set(s)'), which the JP parser keeps
    as the raw getInfo field but never turns into product_names, so the block is read here."""
    from collections import Counter

    from app import collect_official_cardlist_snapshot as collector
    from app.services.official_cardlist import parse_card_list

    try:
        status, body, _ = fetcher.get(ASIA_EN_CARD_LIST)
        if status != 200:
            return {"error": f"Asia-EN card list HTTP {status}"}
        index = parse_card_list(body.decode("utf-8", "replace"), "").series_index
        uncoded = [s for s in index if not ASIA_EN_CODED.search(s.display_name)]
        labels, values, entries, named, pages = Counter(), Counter(), 0, 0, []
        for series in uncoded[:ASIA_EN_MAX_PAGES]:
            status, body, _ = fetcher.get(f"{ASIA_EN_CARD_LIST}?series={series.series_id}")
            if status != 200:
                pages.append([series.series_id, series.display_name, f"HTTP {status}"])
                continue
            page = parse_card_list(body.decode("utf-8", "replace"), series.series_id)
            pages.append([series.series_id, series.display_name, len(page.entries)])
            for entry in page.entries:
                entries += 1
                block = entry.field("getInfo")
                if block is None:
                    continue
                labels[block.label] += 1
                names = [v.strip() for v in (block.value or "").split("\n") if v.strip()]
                if names:
                    named += 1
                values.update(names)
    except collector.CollectionStopped as exc:
        return {"error": f"Asia-EN refused collection: {exc}"}
    return {"series_in_picker": len(index), "uncoded_series": [[s.series_id, s.display_name] for s in uncoded],
            "pages": pages, "entries": entries, "entries_with_obtain_block_values": named,
            "obtain_block_labels": [list(x) for x in labels.most_common(5)],
            "distinct_values": len(values), "top_values": [list(x) for x in values.most_common(limit)]}


# --- plan digest ---------------------------------------------------------------------------

def load_entry_records(root):
    """{entry_id: snapshot record without its fetch time}: the verbatim input the planner and
    the applier's baseline read (name, rarity, effect text, cost, power, ...)."""
    from app.services.official_snapshot import ENTRIES_FILE, Snapshot

    records = {}
    for row in Snapshot(Path(root)).load(ENTRIES_FILE):
        records[row["entry_id"]] = {k: v for k, v in row.items() if k != "fetched_at"}
    return records


def plan_rows(plan, entry_records=None):
    """One sorted row per planned print: the whole PlannedPrint (identity, official metadata,
    proposed card and product) plus the entry record it was planned from, so anything the
    applier would write is covered."""
    entry_records = entry_records or {}
    rows = [{"print": p.to_dict(), "entry": entry_records.get(p.entry_id)} for p in plan.prints]
    return sorted(rows, key=lambda r: (r["print"]["card_code"], r["print"]["entry_id"]))


def plan_sha(scope, rows):
    body = {"scope": scope["name"], "series": scope["series"], "prints": rows}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     default=str).encode()).hexdigest()


def check_sha_shape(expected_sha256):
    if not (isinstance(expected_sha256, str) and re.fullmatch("[0-9a-f]{64}", expected_sha256 or "")):
        raise common.Refused("apply needs expected_sha256: the plan SHA-256 from a dry run")


def check_apply(expected_sha256, sha):
    check_sha_shape(expected_sha256)
    if expected_sha256 != sha:
        raise common.Refused("the plan differs from the dry run's (expected_sha256); dry run again")


# --- target --------------------------------------------------------------------------------

def proxy_url(resolve=None):
    """postgresql URL of the pinned staging Postgres TCP proxy. A credential: every form of it
    (raw and quoted password, both URL schemes) is registered as a secret - masked in the
    Actions log, refused in any output file - and it is never printed. Called before any
    output is redirected, so the mask commands reach the runner."""
    from ops import db as ops_db

    proxy, variables = (resolve or ops_db.resolve)()
    try:
        password = variables["PGPASSWORD"]
        tail = (f"{quote(variables['PGUSER'], safe='')}:{quote(password, safe='')}"
                f"@{proxy['domain']}:{proxy['proxyPort']}/{quote(variables['PGDATABASE'], safe='')}")
        common.register_secret(password)
        common.register_secret(quote(password, safe=""))
    finally:
        variables.clear()
    url = "postgresql://" + tail
    common.register_secret(url)
    common.register_secret("postgresql+psycopg://" + tail)
    return url


# --- run -----------------------------------------------------------------------------------

def parse_report(text):
    """The importer's JSON report: the last top-level object in its stdout."""
    decoder = json.JSONDecoder()
    starts = [0] + [m.end() for m in re.finditer(r"\n(?=\{)", text)]
    for start in reversed(starts):
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            continue
        if isinstance(value, dict) and not text[end:].strip():
            return value
    return None


def import_scope(snapshot_root, scope, *, apply, expected_sha256, main=None, open_tunnel=None):
    """Runs the importer on the scope's coded series; returns (exit code, report, plan facts)."""
    from app.services.canonical_import_apply import STAGING_APPLY_CONFIRMATION

    if main is None:
        from app.import_frozen_bandai_to_canonical_staging import main
    if open_tunnel is None:
        url = proxy_url()  # resolved here, outside the redirect below

        def open_tunnel(_service, _environment):
            return url
    argv = ["--snapshot-root", str(snapshot_root), "--json"]
    for series_id in scope["series"]:
        argv += ["--series", series_id]
    if apply:
        argv += ["--apply", "--confirm", STAGING_APPLY_CONFIRMATION]
    records = load_entry_records(snapshot_root)
    facts = {}

    def on_plan(plan):
        rows = plan_rows(plan, records)
        facts.update(rows=rows, sha=plan_sha(scope, rows), outcomes=plan.counts())
        if apply:
            try:
                check_apply(expected_sha256, facts["sha"])
            except common.Refused as exc:
                facts["refused"] = str(exc)
                raise

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv, open_tunnel=open_tunnel, on_plan=on_plan)
    facts["stderr_tail"] = err.getvalue()[-1500:]
    return code, parse_report(out.getvalue()), facts


REPORT_KEYS = ("applied", "products_created", "product_aliases_created", "canonical_cards_created",
               "card_prints_created", "existing_print_metadata_updated", "plans_total", "eligible_plans",
               "skipped_needs_review", "planner_conflicts", "skipped_no_change", "skipped_ineligible",
               "distinct_image_digests", "rollback_reason", "rollback_detail")


def compact_row(row):
    p = row["print"]
    return " ".join(str(x) for x in (p["card_code"], p["outcome"],
                                     p["official_product_code"] or p["official_product_display_name"],
                                     p["official_asset_variant"] or "-", ",".join(p["flags"]) or "-"))


def _default_fetcher():
    from app import collect_official_cardlist_snapshot as collector

    return collector.RateLimitedFetcher(min_interval=MIN_INTERVAL)


def run(out_dir, *, apply=False, scope="", expected_sha256="", fetcher=None, main=None, open_tunnel=None,
        scopes=None, backup=None, now=common.now_utc):
    import generate_staging_state as state
    from ops import apply_migration

    chosen = resolve_scope(scope, scopes if scopes is not None else load_scopes())
    newest = None
    if apply:
        if not chosen["series"]:
            raise common.Refused(f"scope {chosen['name']!r} has no coded series to import; "
                                 "uncoded products are reported only until Phase 2 step C")
        check_sha_shape(expected_sha256)  # equality is checked on the plan, inside the importer
        # The recovery point: a Railway backup of the staging Postgres volume under 24 hours old,
        # the same rule apply-migration enforces.
        newest = apply_migration.check_backup((backup or apply_migration.newest_backup)())
    root = Path(out_dir) / "snapshot" / "bandai_jp" / "current"
    captured = capture(root, chosen, fetcher=fetcher)
    from app.services.snapshot_planner_input import load_snapshot
    identity = load_snapshot(root).identity
    summary = {"scope": chosen["name"], "apply": bool(apply), "snapshot_identity": identity,
               "capture": captured, "database_writes_possible": bool(apply)}
    if newest is not None:
        summary["backup"] = newest
    # Before the long product lists, so an annotation cut-off loses the least.
    if chosen["asia_en_measure"]:
        summary["asia_en"] = asia_en_measure(fetcher or _default_fetcher())
    products = captured.pop("products", [])
    summary["capture"]["uncoded_products"] = len(products)
    if products:
        from app.services.official_snapshot import ENTRIES_FILE, Snapshot

        rows = uncoded_report(root, products, identity)
        entries = Snapshot(root).load(ENTRIES_FILE)
        summary["uncoded"] = compact_uncoded(rows)
        summary["multi_product_entries"] = multi_product_sets(entries, products)
        missing_excludes = sorted(set(chosen["exclude_products"]) - {n for e in entries for n in e.get("product_names") or ()})
        if missing_excludes:
            summary["exclude_products_not_found"] = missing_excludes
        common.write_json(Path(out_dir) / "uncoded-products.json", rows)
    if not chosen["series"]:
        summary.update(ok=True, plan_sha256=None, note="report only: no coded series in this scope")
        common.write_json(Path(out_dir) / "catalogue-import.json", summary)
        return summary
    if apply:
        # The capture took minutes since the preflight: re-check the windows before writing.
        reason = common.quiet_window_refusal(now(), collector_affecting=True, write=True)
        if reason:
            raise common.Refused(reason)
    code, report, facts = import_scope(root, chosen, apply=apply, expected_sha256=expected_sha256,
                                       main=main, open_tunnel=open_tunnel)
    common.write_json(Path(out_dir) / "catalogue-import.json",
                      {**summary, "exit_code": code, "plan_sha256": facts.get("sha"),
                       "outcomes": facts.get("outcomes"), "prints": facts.get("rows"), "report": report,
                       "observed_at": state.timestamp()})
    rows = facts.get("rows") or []
    summary.update(
        ok=code == 0 and not facts.get("refused"),
        exit_code=code,
        plan_sha256=facts.get("sha"),
        refused=facts.get("refused"),
        outcomes=facts.get("outcomes"),
        report={k: report.get(k) for k in REPORT_KEYS} if isinstance(report, dict) else None,
        prints=[compact_row(r) for r in rows[:ROW_LIMIT]],
        prints_omitted=max(0, len(rows) - ROW_LIMIT))
    if code != 0:
        summary["stderr_tail"] = facts.get("stderr_tail")
    return summary
