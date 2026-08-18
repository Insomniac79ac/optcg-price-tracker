"""CLI: persist verified official Card List display evidence for the migrated prints.

    python -m app.persist_official_display_evidence --manifest <path> --dry-run
    python -m app.persist_official_display_evidence --manifest <path> --persist

The assets are mirrored to R2 by a separate, already-completed step; this
command uploads nothing. What it does is re-prove, per print and immediately
before any write, that the object the evidence is about is really in the
bucket and really is the bytes the manifest claims - and only then record it.

Per asset, stopping at the first failure:

    head     the object exists, with the expected content type, cache policy
             and byte length
    private  authenticated GET: digest == the manifest digest
    public   unauthenticated GET over R2_PUBLIC_BASE_URL: same digest, same
             content type and cache policy
    decode   the public bytes decode to the manifest's exact dimensions
    identity the manifest digest equals card_prints.artwork_key for this print
             - first-party proof that this is the exact printing, checked
             against the database rather than taken on trust

Without --persist nothing is written. With --persist, each verified asset gets
one additive `display_image` block on the official source's mapping for that
print, creating that mapping the first time. Yuyu-Tei and SNKRDUNK evidence
live on different mapping rows and are never read or written here. No
image_url, artwork_key, pricing or Market Index value is written by any path
in this module.

Exit codes:

    0  every asset verified (and, with --persist, recorded)
    1  at least one asset failed verification or persistence
    2  R2 is not configured in this environment
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import urllib.request
from pathlib import Path

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.check_r2_connectivity import scrub
from app.db import SessionLocal
from app.models import CardPrint, SourceCardMapping
from app.services.display_image_object_key import OBJECT_KEY_MEDIA_TYPES, object_key
from app.services.object_storage import R2ConfigurationError, R2ObjectStorage
from app.services.official_display_evidence import (
    VerifiedOfficialAsset,
    persist_display_image,
)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NOT_CONFIGURED = 2

TIMEOUT_SECONDS = 30.0
USER_AGENT = "CardPirateAtlas-official-display-evidence/1.0"


def emit(line: str = "") -> None:
    print(line, flush=True)


def load_manifest(path: Path) -> list[VerifiedOfficialAsset]:
    document = json.loads(path.read_text())
    return [
        VerifiedOfficialAsset(
            card_print_id=e["card_print_id"],
            variant_id=e["variant_id"],
            source_url=e["source_url"],
            sha256=e["sha256"],
            byte_size=e["byte_size"],
            width=e["width"],
            height=e["height"],
            content_type=e["content_type"],
            cache_control=e["cache_control"],
            object_key=e["object_key"],
        )
        for e in document["assets"]
    ]


def verify_asset(asset: VerifiedOfficialAsset, storage: R2ObjectStorage, db: Session):
    """Re-prove the R2 object, and the print identity, before any write."""
    checks: dict[str, bool] = {}
    extension = asset.object_key.rsplit(".", 1)[-1]

    checks["extension_known"] = extension in OBJECT_KEY_MEDIA_TYPES
    checks["content_type_matches_extension"] = (
        checks["extension_known"] and OBJECT_KEY_MEDIA_TYPES[extension] == asset.content_type
    )
    checks["object_key_derives_from_digest"] = asset.object_key == object_key(
        asset.sha256, extension
    )

    print_row = db.get(CardPrint, asset.card_print_id)
    checks["card_print_exists"] = print_row is not None
    # First-party exact-print proof, re-checked against the database.
    checks["digest_equals_artwork_key"] = bool(
        print_row is not None and print_row.artwork_key == asset.sha256
    )
    checks["variant_matches_canonical_url"] = bool(
        print_row is not None
        and print_row.image_url
        and print_row.image_url.split("/")[-1].split("?")[0] == f"{asset.variant_id}.png"
    )

    head = storage.head_object(asset.object_key)
    checks["object_exists"] = head is not None
    checks["head_content_type"] = bool(head and head.content_type == asset.content_type)
    checks["head_cache_control"] = bool(head and head.cache_control == asset.cache_control)
    checks["head_byte_size"] = bool(head and head.content_length == asset.byte_size)

    if head is not None:
        private = storage.get_object_bytes(asset.object_key)
        checks["private_digest"] = hashlib.sha256(private).hexdigest() == asset.sha256

        request = urllib.request.Request(
            storage.public_url(asset.object_key), headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            public = response.read()
            public_type = response.headers.get("Content-Type")
            public_cache = response.headers.get("Cache-Control")
        checks["public_digest"] = hashlib.sha256(public).hexdigest() == asset.sha256
        checks["public_content_type"] = (
            (public_type or "").split(";")[0].strip() == asset.content_type
        )
        checks["public_cache_control"] = public_cache == asset.cache_control
        checks["public_decodes_to_manifest_size"] = Image.open(io.BytesIO(public)).size == (
            asset.width,
            asset.height,
        )

    return [name for name, passed in checks.items() if not passed]


def legacy_card_id(db: Session, card_print_id: int) -> int | None:
    """The legacy cards row this print already maps through.

    Taken from an existing mapping rather than guessed: source_card_mappings
    requires card_id, and it must be the same legacy lineage the print's other
    sources already use.
    """
    return db.execute(
        select(SourceCardMapping.card_id)
        .where(SourceCardMapping.card_print_id == card_print_id)
        .order_by(SourceCardMapping.id.asc())
        .limit(1)
    ).scalar_one_or_none()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="verify only; write nothing")
    mode.add_argument("--persist", action="store_true", help="verify, then record evidence")
    args = parser.parse_args()

    assets = load_manifest(args.manifest)

    try:
        storage = R2ObjectStorage.from_settings()
    except R2ConfigurationError as exc:
        emit(f"[FAIL] not configured: {scrub(str(exc))}")
        sys.exit(EXIT_NOT_CONFIGURED)

    emit(
        f"manifest={args.manifest} assets={len(assets)} bucket={storage.bucket_name!r} "
        f"mode={'PERSIST' if args.persist else 'DRY-RUN'}"
    )
    emit()

    verified: list[VerifiedOfficialAsset] = []
    failed = 0
    db: Session = SessionLocal()
    try:
        for asset in assets:
            failures = verify_asset(asset, storage, db)
            if failures:
                failed += 1
                emit(f"  print {asset.card_print_id:>2}  VERIFY FAIL  {', '.join(failures)}")
            else:
                verified.append(asset)
                emit(f"  print {asset.card_print_id:>2}  VERIFY PASS  {asset.object_key}")

        emit()
        emit(f"verified {len(verified)}/{len(assets)}, failed {failed}")

        if not args.persist:
            emit("\ndry run - nothing was written to the database.")
            sys.exit(EXIT_OK if failed == 0 else EXIT_FAILED)
        if failed:
            emit("\nverification did not pass for every asset - nothing will be written.")
            sys.exit(EXIT_FAILED)

        emit()
        written = already = aborted = created = 0
        for asset in verified:
            card_id = legacy_card_id(db, asset.card_print_id)
            if card_id is None:
                aborted += 1
                emit(f"  print {asset.card_print_id:>2}  ABORTED - no legacy card lineage found")
                continue
            outcome = persist_display_image(db, asset, card_id)
            if outcome.written:
                written += 1
                created += int(outcome.mapping_created)
                state = "WRITTEN" + (" (mapping created)" if outcome.mapping_created else "")
            elif outcome.already_recorded:
                already += 1
                state = "ALREADY RECORDED (no-op)"
            else:
                aborted += 1
                state = f"ABORTED - {outcome.abort_reason}"
            emit(f"  print {asset.card_print_id:>2}  mapping {outcome.mapping_id}  {state}")

        emit()
        emit(
            f"written {written} (mappings created {created}), "
            f"already recorded {already}, aborted {aborted}"
        )
        sys.exit(EXIT_OK if aborted == 0 else EXIT_FAILED)
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
