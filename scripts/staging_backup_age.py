#!/usr/bin/env python3
"""Require a staging Postgres volume backup younger than --max-hours.

Read-only Railway queries with the staging-delivery RAILWAY_TOKEN; prints only
backup IDs, timestamps and ages, never credentials. Exit 1 when no backup is
young enough or the backups cannot be read (fail closed). Used before arming a
PRODUCT-lane PR that adds a migration (docs/agent/STAGING_DELIVERY.md).
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import generate_staging_state as state

VOLUME = "postgres-volume"


def newest_backup(now=None):
    now = now or datetime.now(timezone.utc)
    volumes = state.railway(
        f'query {{ project(id:"{state.PROJECT}") {{ volumes {{ edges {{ node {{ name '
        'volumeInstances { edges { node { id environmentId } } } } } } } }'
    )["project"]["volumes"]["edges"]
    instances = [vi["node"]["id"] for v in volumes if v["node"]["name"] == VOLUME
                 for vi in v["node"]["volumeInstances"]["edges"]
                 if vi["node"]["environmentId"] == state.ENVIRONMENT]
    if len(instances) != 1:
        raise state.VerificationError("Ambiguous staging Postgres volume")
    backups = state.railway(
        f'query {{ volumeInstanceBackupList(volumeInstanceId:"{instances[0]}") {{ id createdAt }} }}'
    )["volumeInstanceBackupList"]
    if not backups:
        return None
    newest = max(backups, key=lambda b: b["createdAt"])
    created = datetime.fromisoformat(newest["createdAt"].replace("Z", "+00:00"))
    return {"id": newest["id"], "created_at": newest["createdAt"],
            "age_hours": round((now - created).total_seconds() / 3600, 2)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-hours", type=float, default=24)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        newest = newest_backup()
        ok = newest is not None and 0 <= newest["age_hours"] < args.max_hours
        result = {"newest": newest, "max_hours": args.max_hours, "backup_ok": ok}
    except (state.VerificationError, KeyError, TypeError, ValueError) as exc:
        result = {"newest": None, "max_hours": args.max_hours, "backup_ok": False,
                  "error": type(exc).__name__}
    text = json.dumps(result, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    return 0 if result["backup_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
