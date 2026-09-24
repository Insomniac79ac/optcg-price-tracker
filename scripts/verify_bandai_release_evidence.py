#!/usr/bin/env python3
"""Offline verification of the Public UX 1A-API3 Bandai evidence bundle.

Requires beautifulsoup4 (already in worker/collector development requirements).
Reads preserved response bodies before extracting anything. No HTTP, database,
application imports, or file writes. JSON output is an evidence audit; the
chronology preview is computed separately and printed only with --preview.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


VERSION = "bandai_release_evidence_audit_v2"
FAMILIES = {"OP": 17, "EB": 4, "PRB": 2, "ST": 36}
LABELS = {"発売日", "発売予定日"}
DEFAULT_ROOT = Path("data/official_snapshots/bandai_jp/release_dates/2026-09-24_api3")
DATE_PATTERN = re.compile(r"(?<!\d)(\d{4})[.年](\d{1,2})[.月](\d{1,2})(?:日)?(?!\d)")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def normalized(text):
    # Typography only; no fuzzy matching, token removal, or name inference.
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def dates_in(text):
    return sorted({date(*map(int, m.groups())).isoformat() for m in DATE_PATTERN.finditer(normalized(text))})


def official_url(url):
    parts = urlsplit(url)
    require(parts.scheme == "https" and parts.netloc == "www.onepiece-cardgame.com", f"Non-JP official URL: {url}")
    require(parts.path.startswith("/products/"), f"Not a product source: {url}")


def verify_raw(root, record):
    require(record["source_catalogue"] == "bandai_jp", "Wrong source catalogue")
    official_url(record["source_url"])
    official_url(record["final_url"])
    stamp = datetime.fromisoformat(record["fetched_at"])
    require(stamp.utcoffset() == timedelta(0), "Fetch time must be UTC")
    path = (root / record["raw_path"]).resolve()
    require(path.is_relative_to(root.resolve()), "Raw path escapes evidence bundle")
    raw = gzip.decompress(path.read_bytes())
    require(hashlib.sha256(raw).hexdigest() == record["sha256"], f"Digest mismatch: {record['label']}")
    require(len(raw) == record["byte_length"], f"Length mismatch: {record['label']}")
    require(bool(record["parser_version"]), "Missing acquisition parser version")
    require(record["content_type"].split(";")[0] == "text/html", "Unexpected content type")
    return raw


def extract_detail(raw, identity):
    soup = BeautifulSoup(raw, "html.parser")
    scopes = soup.select(".prodStatusCol, .detailColStatus, .productStatus")
    exact_name = normalized(identity["display_name"])
    scopes = [s for s in scopes if exact_name in normalized(s.get_text(" ", strip=True))]
    require(len(scopes) == 1, f"Ambiguous product detail identity: {identity['official_code']}")
    scope = scopes[0]
    require(identity["official_code"] in scope.get_text(), "Product code absent from product details")
    observations = []
    for label in scope.find_all(["h4", "dt", "th"]):
        if label.get_text(strip=True) not in LABELS:
            continue
        value = label.find_next_sibling()
        require(value is not None, "Release label has no value")
        observations.append({
            "published_label": label.get_text(strip=True),
            "published_value": value.get_text(" ", strip=True),
            "dates": dates_in(value.get_text(" ", strip=True)),
            "locator": f".{scope.get('class')[0]} {label.name} (exact release label) + sibling",
        })
    require(observations and all(x["dates"] for x in observations), f"No explicit release date: {identity['official_code']}")
    return observations


def extract_index(raw, identity, detail_url):
    soup = BeautifulSoup(raw, "html.parser")
    exact_name = normalized(identity["display_name"])
    entries = [n for n in soup.select("a.linkListColItem")
               if n.select_one(".linkListColTitle") is not None
               and normalized(n.select_one(".linkListColTitle").get_text(" ", strip=True)) == exact_name]
    require(len(entries) == 1, f"Ambiguous index identity: {identity['official_code']}")
    entry = entries[0]
    require(entry.get("href") == detail_url, "Index and detail page identity URLs disagree")
    block = entry.select_one(".linkListColDate")
    require(block is not None, "Index release date absent")
    label, value = block.select_one(".head"), block.select_one("time")
    require(label is not None and label.get_text(strip=True) in LABELS, "Index date is not labelled as release")
    require(value is not None, "Index release date value absent")
    dates = dates_in(value.get_text(" ", strip=True))
    require(dates == [value.get("datetime")], "Index visible date and datetime disagree")
    return [{"published_label": label.get_text(strip=True),
             "published_value": value.get_text(" ", strip=True), "dates": dates,
             "locator": "a.linkListColItem (exact title and href) .linkListColDate time"}]


def classify(evidence):
    dates = {d for item in evidence for observation in item["observations"] for d in observation["dates"]}
    require(dates, "No accepted dated evidence")
    if len(dates) > 1:
        return "DATE_CONFLICT", None
    count = len({item["source_url"] for item in evidence})
    return ("DATE_VERIFIED_CORROBORATED" if count > 1 else "DATE_VERIFIED_SINGLE_SOURCE"), next(iter(dates))


def audit(root):
    inventory_path = root / "release_products_staging.json"
    inventory_bytes = inventory_path.read_bytes()
    inventory = json.loads(inventory_bytes)
    products = inventory["rows"]
    require(len({p["release_product_id"] for p in products}) == len(products), "Duplicate ReleaseProduct IDs")
    require(all(p["source_catalogue"] == "bandai_jp" for p in products), "Non-JP inventory row")
    target_codes = [f"{family}-{i:02}" for family, count in FAMILIES.items() for i in range(1, count + 1)]
    identities = {p["official_code"]: p for p in products if p["official_code"] is not None}
    require(len(identities) == sum(p["official_code"] is not None for p in products), "Duplicate product code")
    require(set(identities) == set(target_codes), "Coded inventory differs from requested scope")
    records = {}
    bodies = {}
    for path in sorted((root / "records").glob("*.json")):
        record = json.loads(path.read_text())
        require(record["label"] not in records, "Duplicate acquisition record")
        bodies[record["label"]] = verify_raw(root, record)
        records[record["label"]] = record
    recorded_paths = {r["raw_path"] for r in records.values()}
    require(recorded_paths == {str(p.relative_to(root)) for p in (root / "raw").glob("*")}, "Unreferenced or absent raw payload")
    legacy = [json.loads(line) for line in (root / "release_date_evidence.jsonl").read_text().splitlines()]
    require(len(legacy) == len(target_codes), "Missing or duplicate evidence rows")
    by_code = {r["official_code"]: r for r in legacy}
    require(set(by_code) == set(target_codes), "Incomplete evidence code coverage")
    verified = []
    family_checks = []
    for family, count in FAMILIES.items():
        for i in range(1, count + 1):
            code = f"{family}-{i:02}"
            row, identity = by_code[code], identities[code]
            for key in ("release_product_id", "official_code", "source_catalogue", "display_name", "source_series_id"):
                require(row[key] == identity[key], f"Identity mismatch: {code}/{key}")
            evidence = []
            require(row["evidence"], f"No evidence references: {code}")
            for ref in row["evidence"]:
                record = records[ref["evidence_id"]]
                for key in ("source_url", "final_url", "fetched_at", "http_status", "content_type", "sha256", "raw_path", "byte_length", "parser_version"):
                    require(ref[key] == record[key], f"Evidence metadata mismatch: {code}/{key}")
                require(record["http_status"] == 200, f"Non-success evidence accepted: {code}")
                is_index = record["label"].startswith("products-index")
                observations = (extract_index(bodies[record["label"]], identity, row["primary_official_url"])
                                if is_index else extract_detail(bodies[record["label"]], identity))
                fetched_date = datetime.fromisoformat(record["fetched_at"]).date()
                for observation in observations:
                    observation["date_provenance"] = (
                        "published_scheduled_release_date" if observation["published_label"] == "発売予定日"
                        else "published_product_release_date")
                    observation["temporal_status_at_fetch"] = {
                        d: "future" if date.fromisoformat(d) > fetched_date else "on_or_before_fetch"
                        for d in observation["dates"]}
                evidence.append({**identity, **ref,
                                 "evidence_id": f"{code}:{record['label']}",
                                 "acquisition_record_id": record["label"],
                                 "source_role": "official_product_index" if is_index else "official_product_detail",
                                 "extractor_version": VERSION,
                                 "identity_rule": "catalogue + exact code + product details/index identity + typography-normalized full display name",
                                 "observations": observations})
            classification, accepted_date = classify(evidence)
            require(row["classification"] == classification and row["release_date"] == accepted_date,
                    f"Prior derived conclusion differs from raw evidence: {code}: {classification}/{accepted_date}")
            primary = evidence[0]
            for row_key, ref_key in (("primary_official_url", "source_url"), ("raw_evidence_path", "raw_path"),
                                     ("sha256", "sha256"), ("fetched_at", "fetched_at")):
                require(row[row_key] == primary[ref_key], f"Primary reference mismatch: {code}")
            require(row["evidence_source_count"] == len({e['source_url'] for e in evidence}), "Invalid evidence count")
            notes = ["Exact official product identity; explicitly labelled 発売日; no article timestamp used."]
            if code == "EB-04":
                notes.append("Successful legacy product URL; absent from preserved current index. Guessed /products/eb04.html returned 404 (retained as discovery only).")
            if code == "OP-02":
                notes.append("Bandai explicitly says the release date changed from its initial announcement; use the displayed final 2022-11-04. No earlier date is given in this record.")
            if code in {f"ST-{n:02}" for n in (*range(1, 5), *range(15, 21))}:
                notes.append("Shared official page explicitly lists this exact deck name/code and one common release date.")
            if code in {f"ST-{n:02}" for n in range(31, 37)}:
                notes.append("Detail date omits the 日 character; visible Y/M/D agrees with the explicitly labelled index date.")
            verified.append({**row, "extractor_version": VERSION, "evidence": evidence, "notes": " ".join(notes)})
        family_rows = [r for r in verified if r["official_code"].startswith(family + "-")]
        family_checks.append({"family": family, "total": count,
                              "dated": sum(r["classification"].startswith("DATE_VERIFIED_") for r in family_rows),
                              "missing": 0, "conflicts": sum(r["classification"] == "DATE_CONFLICT" for r in family_rows),
                              "identity_digest_date_checks": "passed"})
    conflicts = [{"release_product_id": r["release_product_id"], "official_code": r["official_code"],
                  "evidence": r["evidence"]} for r in verified if r["classification"] == "DATE_CONFLICT"]
    summary = {
        "status": "PUBLIC_UX_1A_RELEASE_EVIDENCE_CONFLICT" if conflicts else "PUBLIC_UX_1A_RELEASE_EVIDENCE_READY",
        "audit_version": VERSION, "audited_at": datetime.now(timezone.utc).isoformat(),
        "identity_inventory_source": inventory["source"], "identity_inventory_read_at": inventory["read_at"],
        "identity_inventory_sha256": hashlib.sha256(inventory_bytes).hexdigest(),
        "inventory_rows": len(products), "coded_products": len(verified),
        "uncoded_fallback": [p for p in products if p["official_code"] is None],
        "family_validation_order": family_checks,
        "classifications": dict(Counter(r["classification"] for r in verified)),
        "raw_acquisition_records_verified": len(records), "unique_raw_payloads_verified": len(recorded_paths),
        "compressed_raw_bytes": sum((root / p).stat().st_size for p in recorded_paths),
        "product_evidence_associations": sum(len(r["evidence"]) for r in verified),
        "http_statuses": dict(Counter(r["http_status"] for r in records.values())),
        "fetch_window_utc": [min(r["fetched_at"] for r in records.values()), max(r["fetched_at"] for r in records.values())],
        "missing_products": [], "conflicts": conflicts,
        "safety": "Offline read-only audit. No network, DB, application, migration, deployment, or infrastructure access.",
    }
    return {"summary": summary, "rows": verified}, products


def preview(rows, products):
    dated = {r["release_product_id"]: r["release_date"] for r in rows if r["classification"].startswith("DATE_VERIFIED_")}
    def key(product):
        released = dated.get(product["release_product_id"])
        return (released is None, -date.fromisoformat(released).toordinal() if released else 0,
                product["official_code"] or "", product["release_product_id"])
    ordered = sorted(products, key=key)
    for position, product in enumerate(ordered[:30], 1):
        print(f"{position:2}. {dated.get(product['release_product_id'], 'NULL')} | {product['official_code']} | ID {product['release_product_id']} | {product['display_name']}")
    print("Undated fallback (ID ascending; all coded products are dated):")
    for product in ordered:
        if product["release_product_id"] not in dated:
            print(f"{product['release_product_id']} | {product['display_name']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--preview", action="store_true", help="Print in-memory chronology instead of evidence JSON")
    args = parser.parse_args()
    result, products = audit(args.root)
    if args.preview:
        preview(result["rows"], products)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
