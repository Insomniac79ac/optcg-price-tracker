"""Run one named, reviewed SQL file from scripts/diagnostics/ over a read-only staging session.

A diagnostic file holds one or more statements, each introduced by a `-- name` line and ended
by `;` (the format of docs/agent/evidence/staging-state-read.sql). Every statement must be a
SELECT or WITH query and may not contain a write or session keyword; the read-only
transaction (default_transaction_read_only=on) remains the enforcement. `{{ELIGIBLE}}` expands
to the shared operational-health population (app.services.operational_health_sql.ELIGIBLE).
Adding a diagnostic is a reviewed PR; there is no free-form SQL input.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from ops import common

DIRECTORY = common.ROOT / "scripts/diagnostics"
# Rows small enough for the ops-summary annotations (9 x 3000 characters) go into the summary, so
# an agent reads them over REST; a larger statement keeps only its count (rows in the artifact).
INLINE_CHARS = 18000
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|upsert|truncate|drop|alter|create|grant|revoke|copy|vacuum|analyze"
    r"|reindex|cluster|lock|set|reset|begin|commit|rollback|savepoint|call|do|execute|prepare|listen|notify"
    r"|refresh|security|pg_terminate_backend|pg_cancel_backend|pg_reload_conf|lo_import|lo_export"
    r"|pg_read_file|pg_read_binary_file|pg_ls_dir|dblink|nextval|setval|set_config|pg_notify"
    r"|pg_advisory\w*|pg_try_advisory\w*|txid_current|pg_switch_wal|pg_create\w*|pg_drop\w*)\b", re.I)


def available():
    return sorted(p.stem for p in DIRECTORY.glob("*.sql") if NAME.fullmatch(p.stem))


def fragments():
    from app.services.operational_health_sql import ELIGIBLE

    return {"ELIGIBLE": ELIGIBLE}


def _strip_comments(sql):
    return re.sub(r"--[^\n]*", "", sql)


def parse(text, expand=None):
    """{name: sql} or Refused. Validation runs on the file text, before expansion."""
    statements = dict(re.findall(r"^-- ([a-z0-9_]+)\n(.*?);\s*$", text, re.M | re.S))
    if not statements:
        raise common.Refused("no named statements")
    out = {}
    for name, sql in statements.items():
        body = _strip_comments(sql).strip()
        if not body.lower().startswith(("select", "with")):
            raise common.Refused(f"{name}: only SELECT/WITH statements")
        if ";" in body:
            raise common.Refused(f"{name}: one statement per name")
        hit = FORBIDDEN.search(re.sub(r"'[^']*'", "''", body))
        if hit:
            raise common.Refused(f"{name}: forbidden keyword {hit.group(0)!r}")
        for key in re.findall(r"\{\{(\w+)\}\}", body):
            if expand is None or key not in expand:
                raise common.Refused(f"{name}: unknown fragment {key}")
            body = body.replace("{{" + key + "}}", expand[key])
        out[name] = body
    return out


def load(name):
    if not NAME.fullmatch(name or "") or name not in available():
        raise common.Refused(f"unknown diagnostic {name!r}; available: {', '.join(available())}")
    text = (DIRECTORY / f"{name}.sql").read_text()
    return parse(text, fragments() if "{{" in text else None)


def execute(conn, statements, row_limit=500):
    out = {}
    for name, sql in statements.items():
        rows = conn.execute(sql).fetchmany(row_limit + 1)
        out[name] = {"rows": rows[:row_limit], "truncated": len(rows) > row_limit}
    conn.rollback()
    return out


def run(out_dir, name):
    from ops import db as ops_db

    statements = load(name)
    with ops_db.connection() as conn:
        result = execute(conn, statements)
    common.write_json(Path(out_dir) / f"diagnostic-{name}.json",
                      {"diagnostic": name, "read_only": True, "database_writes": 0, "results": result})
    return {"diagnostic": name, "statements": {k: len(v["rows"]) for k, v in result.items()},
            "truncated": sorted(k for k, v in result.items() if v["truncated"]), **inline(result)}


def inline(result, limit=INLINE_CHARS):
    """{"rows": {name: {columns, rows}}, "rows_omitted": [...]}, statements in order until the budget is spent."""
    rows, omitted, used = {}, [], 0
    for name, value in result.items():
        table = {"columns": list(value["rows"][0]) if value["rows"] else [],
                 "rows": [list(row.values()) for row in value["rows"]]}
        size = len(json.dumps(table, separators=(",", ":"), default=common.json_default))
        if used + size > limit:
            omitted.append(name)
            continue
        rows[name] = table
        used += size
    return {"rows": rows, "rows_omitted": omitted}
