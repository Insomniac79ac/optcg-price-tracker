"""CLI: report prints missing a verified R2 copy of their official image.

    python -m app.check_official_images                    # database consistency
    python -m app.check_official_images --verify-objects   # also HEAD every object

Read-only. A healthy run prints nothing and exits 0. Otherwise it prints a JSON
summary and exits 1 (2 when --verify-objects is asked for without R2 config).
"""

from __future__ import annotations

import argparse
import json
import sys

from app.db import SessionLocal
from app.official_images.health import check_health
from app.services.object_storage import R2ConfigurationError, R2ObjectStorage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify-objects", action="store_true")
    args = parser.parse_args(argv)
    storage = None
    if args.verify_objects:
        try:
            storage = R2ObjectStorage.from_settings()
        except R2ConfigurationError as exc:
            print(f"R2 not configured: {exc}", file=sys.stderr)
            return 2
    with SessionLocal() as db:
        report = check_health(db, storage)
    if report.healthy:
        return 0
    print(json.dumps(report.summary(), indent=1))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
