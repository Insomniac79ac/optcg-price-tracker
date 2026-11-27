"""Read-only staging database connection check.

Reports whether the session is encrypted (and if so, the protocol and cipher),
then a separate read-only fingerprint. Never prints a host, port, user,
password or connection string. Driver errors are reported by class only.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from ops import common, db as ops_db


def _encryption(connection):
    """True/false plus protocol and cipher from the current backend; no connection details."""
    row = connection.execute(
        "SELECT ssl, version, cipher FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
    ).fetchone()
    if not row:
        return {"negotiated": False}
    ssl, version, cipher = row[0], row[1], row[2]
    result = {"negotiated": bool(ssl)}
    if version:
        result["protocol"] = str(version)
    if cipher:
        result["cipher"] = str(cipher)
    return result


def _open(kwargs):
    import psycopg
    return psycopg.connect(**kwargs)


def run(out_dir):
    from generate_staging_state import db_failure_class

    proxy, variables = ops_db.resolve()
    try:
        kwargs = ops_db.connect_kwargs(proxy, variables)
        kwargs["sslmode"] = "require"
    finally:
        variables.clear()
    try:
        connection = _open(kwargs)
    except Exception as error:
        raise common.Refused(
            f"staging database connection failed ({db_failure_class(error)})"
        ) from None
    finally:
        kwargs.clear()
    connection.read_only = True

    try:
        try:
            tls = _encryption(connection)
            connection.rollback()
        except common.Refused:
            raise
        except Exception as error:
            raise common.Refused(
                f"session encryption check failed ({db_failure_class(error)})"
            ) from None
        try:
            ops_db.verify(connection)
        except common.Refused as error:
            result = {"tls": tls, "fingerprint": {"ok": False, "reason": str(error)}}
        else:
            result = {"tls": tls, "fingerprint": {"ok": True}}
    finally:
        connection.close()

    common.write_json(Path(out_dir) / "connection-check.json", result)
    return result


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("ops-out"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        result = run(args.out)
        print(json.dumps({"status": "ok", "result": result}, indent=1))
    except common.Refused as error:
        print(json.dumps({"status": "refused", "reason": str(error)}, indent=1))
        raise SystemExit(2)
