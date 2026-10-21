"""Read-only sibling-encoding sample: what RAW_DICTIONARY_SIBLING=true would store (no writes).

For each parser, the newest retained plaintext 200 rows of the last 7 days (no active ledger
encoding) are paired the way the writer would pair them: an older plaintext row at the same URL
first, else the newest older plaintext sibling of the same URL class. Each pair is encoded in
memory with the package encoder (which rebuilds every byte before returning) and measured. The
flip gate is the median encoded size: Yuyu listings <=10 KB, SNKRDUNK discovery <=16 KB.
Read-only: no database writes, no source requests.
"""
from __future__ import annotations

from pathlib import Path
import statistics

from ops import common

KB = 1024
# parser: median encoded-bytes gate (None = reported, not gated)
PARSERS = {
    "yuyutei-collector-v3": 10 * KB,
    "snkr-published-discovery-v1": 16 * KB,
    "yuyutei-recurring-discovery-v1": None,
}
SAMPLE = 50
CANDIDATES = 400
MIN_PAIRS = 10

CANDIDATE_SQL = """select r.id, r.source_id, r.source_url, pg_column_size(r.raw_content) stored_bytes
  from raw_snapshots r where r.parser_version=%s and r.http_status=200
  and r.fetched_at >= now() - interval '7 days'
  and not exists (select 1 from raw_snapshot_dictionaries d where d.id=r.id and d.expanded_at is null)
  order by r.id desc limit %s"""
BODY_SQL = "select id, raw_content, content_hash from raw_snapshots where id = any(%s)"


def pairs(candidates, url_class, sample=SAMPLE):
    """[(row, base, kind)] for the newest rows with an older same-URL or sibling plaintext base."""
    out = []
    for index, row in enumerate(candidates):
        older = [c for c in candidates[index + 1:] if c["source_id"] == row["source_id"]]
        same = next((c for c in older if c["source_url"] == row["source_url"]), None)
        wanted = url_class(row["source_url"])
        sibling = next((c for c in older if c["source_url"] != row["source_url"]
                        and url_class(c["source_url"]) == wanted), None)
        if same or sibling:
            out.append((row, same or sibling, "same_url" if same else "sibling"))
        if len(out) >= sample:
            break
    return out


def percentile(values, share):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))] if ordered else None


def measure(db, parser, gate, *, encode, sha256, url_class, prefix):
    candidates = db.execute(CANDIDATE_SQL, (parser, CANDIDATES)).fetchall()
    chosen = pairs(candidates, url_class)
    ids = sorted({p[0]["id"] for p in chosen} | {p[1]["id"] for p in chosen})
    bodies = {r["id"]: r for r in db.execute(BODY_SQL, (ids,)).fetchall()} if ids else {}
    encoded, stored, text_bytes, admitted, kinds, errors = [], [], [], 0, {"same_url": 0, "sibling": 0}, 0
    for row, base, kind in chosen:
        child, parent = bodies.get(row["id"]), bodies.get(base["id"])
        try:
            body, base_body = child["raw_content"].encode(), parent["raw_content"].encode()
            if (child["raw_content"].startswith(prefix) or parent["raw_content"].startswith(prefix)
                    or sha256(body) != child["content_hash"] or sha256(base_body) != parent["content_hash"]):
                raise ValueError("not retained plaintext")
            size = len(encode(body, base_id=base["id"], base_body=base_body).encode())
        except Exception:  # noqa: BLE001 - counted, never printed (bodies stay in the database)
            errors += 1
            continue
        kinds[kind] += 1
        encoded.append(size)
        stored.append(row["stored_bytes"])
        text_bytes.append(len(body))
        # The writer's savings rule: at least 25% below the base's stored bytes.
        admitted += size * 4 <= base["stored_bytes"] * 3
    median = statistics.median(encoded) if encoded else None
    result = {"candidates": len(candidates), "pairs": len(encoded), "errors": errors, "kinds": kinds,
              "median_encoded_bytes": median, "p90_encoded_bytes": percentile(encoded, 0.9),
              "median_stored_bytes_now": statistics.median(stored) if stored else None,
              "median_text_bytes": statistics.median(text_bytes) if text_bytes else None,
              "admitted_by_savings_rule": admitted, "gate_bytes": gate}
    if median is not None and stored:
        result["stored_saving_share"] = round(1 - sum(encoded) / sum(stored), 3)
    if gate is not None:
        result["gate_pass"] = len(encoded) >= MIN_PAIRS and median <= gate
    return result


def sample(db):
    from app.services.raw_dictionary_storage import url_class
    from opcg_source_identity.raw_payload import PREFIX, encode, sha256

    res = {"target": "staging", "read_only": True, "source_requests": 0, "database_writes": 0,
           "min_pairs": MIN_PAIRS, "parsers": {}}
    for parser, gate in PARSERS.items():
        res["parsers"][parser] = measure(db, parser, gate, encode=encode, sha256=sha256,
                                         url_class=url_class, prefix=PREFIX)
    db.rollback()
    res["gate_pass"] = all(v["gate_pass"] for v in res["parsers"].values() if "gate_pass" in v)
    return res


def run(out_dir):
    from ops import db as ops_db

    with ops_db.connection(statement_timeout_ms=120000) as conn:
        result = sample(conn)
    common.write_json(Path(out_dir) / "encoding-sample.json", result)
    return result
