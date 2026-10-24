"""Lossless verification of daily-v1 RAW ledger rows above a floor (session 13 tools/verify_all.py).

Each encoded row is rebuilt twice, by an independent zstd path and by the package decoder;
both must match the ledger original_sha256/bytes and the snapshot content_hash. Expanded rows
must hash to the same value. Read-only: no writes, no source requests.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from ops import common

BATCH = 100
BASE_CACHE = 400


def sha(data):
    return hashlib.sha256(data).hexdigest()


def independent(stored, base, prefix):
    import zstandard as zstd

    env = json.loads(stored[len(prefix):])
    comp = base64.b64decode(env["data"], validate=True)
    dictionary = zstd.ZstdCompressionDict(base, dict_type=zstd.DICT_TYPE_RAWCONTENT)
    return env, zstd.ZstdDecompressor(dict_data=dictionary).decompress(comp, max_output_size=16 * 1024**2)


def base_body(base_row, bottom_row, *, prefix, decode):
    """Plaintext bytes of a base: its own text, or an anchor rebuilt from its plaintext bottom."""
    if not base_row["raw_content"].startswith(prefix):
        return base_row["raw_content"].encode()
    bottom = bottom_row["raw_content"].encode()
    _, independent_body = independent(base_row["raw_content"], bottom, prefix)
    package = decode(base_row["raw_content"], expected_hash=base_row["content_hash"], load_base=lambda _: bottom)
    if package != independent_body:
        raise ValueError("anchor rebuilds disagree")
    return package


def check_row(row, base_row, *, prefix, decode, bottom_row=None):
    """{check: bool} for one encoded ledger row against its base snapshot.

    The base is plaintext (same URL, or a sibling URL of the same source and parser), or an
    anchor: the same URL's encoded first check, whose own base (bottom_row) is plaintext.
    """
    stored = row["stored"]
    anchor = base_row["raw_content"].startswith(prefix)
    same_family = (row["source_id"], row["parser_version"]) == (base_row["source_id"], base_row["parser_version"])
    bounded = (not anchor or (bottom_row is not None and row["source_url"] == base_row["source_url"]
                              and not bottom_row["raw_content"].startswith(prefix)
                              and bottom_row["id"] < base_row["id"]
                              and (bottom_row["source_id"], bottom_row["parser_version"])
                              == (base_row["source_id"], base_row["parser_version"])))
    checks = {"encoded": stored.startswith(prefix),
              "base_older_same_scope": base_row["id"] < row["id"] and same_family and bounded}
    try:
        base = base_body(base_row, bottom_row, prefix=prefix, decode=decode)
        checks["base_hash"] = sha(base) == base_row["content_hash"] == row["base_sha256"]
    except Exception as exc:  # noqa: BLE001 - a decode failure is a failed check
        checks.update(base_decode_ok=False, error=type(exc).__name__)
        base = b""
    try:
        env, body = independent(stored, base, prefix)
        package = decode(stored, expected_hash=row["content_hash"], load_base=lambda _: base)
        checks.update({
            "envelope_base_id": env["base_id"] == base_row["id"],
            "independent_sha": sha(body) == row["original_sha256"] == row["content_hash"] == env["sha256"],
            "independent_len": len(body) == row["original_bytes"] == env["byte_length"],
            "package_equals_independent": package == body,
        })
    except Exception as exc:  # noqa: BLE001 - a decode failure is a failed check
        checks["decode_ok"] = False
        checks["error"] = type(exc).__name__
    checks["encoded_bytes"] = len(stored.encode()) == row["encoded_bytes"]
    checks["http200"] = row["http_status"] == 200
    return checks


BOTTOM_SQL = """select r.id, r.raw_content, r.content_hash, r.source_url, r.source_id, r.parser_version
  from raw_snapshot_dictionaries d join raw_snapshots r on r.id=d.base_snapshot_id where d.id=%s"""
LEDGER_SQL = """select d.*, r.source_url, r.source_id, r.parser_version, r.http_status, r.content_hash,
  r.raw_content stored, s.name source from raw_snapshot_dictionaries d join raw_snapshots r on r.id=d.id
  join sources s on s.id=r.source_id where d.id > %s and d.id <= %s order by d.id limit %s"""
BASE_SQL = "select id, raw_content, content_hash, source_url, source_id, parser_version from raw_snapshots where id=%s"


def verify(db, floor, *, prefix=None, decode=None, batch=BATCH, progress=print):
    if prefix is None or decode is None:
        from opcg_source_identity.raw_payload import PREFIX, decode as package_decode
        prefix, decode = prefix or PREFIX, decode or package_decode
    res = {"target": "staging", "read_only": True, "source_requests": 0, "database_writes": 0,
           "ledger_id_floor_exclusive": floor, "failures": [], "expanded": [], "by_source": {}}
    res["ledger_max_id"] = db.execute("select max(id) m from raw_snapshot_dictionaries").fetchone()["m"] or floor
    bases, ok, n, last = {}, True, 0, floor
    while True:
        rows = db.execute(LEDGER_SQL, (last, res["ledger_max_id"], batch)).fetchall()
        if not rows:
            break
        for r in rows:
            last = r["id"]
            n += 1
            agg = res["by_source"].setdefault(r["source"], {"rows": 0, "original_bytes": 0, "encoded_bytes": 0})
            agg["rows"] += 1
            agg["original_bytes"] += r["original_bytes"]
            agg["encoded_bytes"] += r["encoded_bytes"]
            stored = r["stored"]
            if r["expanded_at"] is not None and not stored.startswith(prefix):
                good = sha(stored.encode()) == r["original_sha256"] == r["content_hash"]
                res["expanded"].append({"id": r["id"], "ok": good})
                ok &= good
                continue
            bid = r["base_snapshot_id"]
            if bid not in bases:
                bases[bid] = db.execute(BASE_SQL, (bid,)).fetchone()
                if len(bases) > BASE_CACHE:
                    bases.pop(next(iter(bases)))
            bottom = None
            if bases[bid] is not None and bases[bid]["raw_content"].startswith(prefix):
                bottom = db.execute(BOTTOM_SQL, (bid,)).fetchone()
                res["anchored"] = res.get("anchored", 0) + 1
            checks = check_row(r, bases[bid], prefix=prefix, decode=decode, bottom_row=bottom)
            if not all(v for k, v in checks.items() if k != "error"):
                res["failures"].append({"id": r["id"], "checks": checks})
                ok = False
        progress(f"verified through {last} ({n} rows), failures={len(res['failures'])}")
    db.rollback()
    res["rows_checked"] = n
    res["last_id"] = last
    res["next_floor_exclusive"] = last
    res["all_lossless"] = ok and n > 0
    return res


def run(out_dir, floor):
    from ops import db as ops_db

    if type(floor) is not int or floor < 0:
        raise common.Refused("ledger floor must be a non-negative integer")
    with ops_db.connection(statement_timeout_ms=120000) as conn:
        result = verify(conn, floor)
    common.write_json(Path(out_dir) / f"verify-lossless-from-{floor}.json", result)
    return {k: result[k] for k in ("ledger_id_floor_exclusive", "ledger_max_id", "rows_checked", "next_floor_exclusive",
                                    "all_lossless")} | {"failures": len(result["failures"]),
                                                        "expanded": len(result["expanded"]),
                                                        "by_source": {s: v["rows"] for s, v in result["by_source"].items()}}
