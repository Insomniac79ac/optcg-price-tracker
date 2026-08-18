"""CLI: persist verified Yuyu-Tei display evidence for the migrated prints.

    python -m app.persist_yuyutei_display_evidence --manifest <path> --dry-run
    python -m app.persist_yuyutei_display_evidence --manifest <path> --persist

The assets are mirrored to R2 by a separate, already-completed step; this
command does not upload anything and cannot. What it does is re-prove, per
print and immediately before any write, that the object the evidence is about
is really in the bucket and really is the bytes the manifest claims - and
only then record it.

Per asset, stopping at the first failure:

    head     the object exists, with the expected content type, cache policy
             and byte length
    private  authenticated GET: digest == the manifest digest
    public   unauthenticated GET over R2_PUBLIC_BASE_URL: same digest, same
             content type and cache policy
    decode   the public bytes decode to the manifest's exact dimensions -
             the natural size the frontend geometry guard depends on

Without --persist nothing whatsoever is written: --dry-run runs every check
and reports what *would* be recorded. Persistence is never the default.

With --persist, each verified asset gets one additive `display_image` block
on its Yuyu-Tei mapping. An identical block is left completely alone,
`verified_at` included, so re-running is a no-op; a conflicting one is a hard
failure for that print and is never overwritten. SNKRDUNK evidence lives on
different mapping rows and is not read, written or touched here. No
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
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from sqlalchemy.orm import Session

from app.check_r2_connectivity import scrub
from app.db import SessionLocal
from app.services.display_image_object_key import OBJECT_KEY_MEDIA_TYPES, object_key
from app.services.object_storage import (
    R2ConfigurationError,
    R2ObjectStorage,
)
from app.services.yuyutei_display_evidence import (
    VerifiedYuyuteiAsset,
    persist_display_image,
)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NOT_CONFIGURED = 2

PUBLIC_FETCH_TIMEOUT_SECONDS = 30.0
USER_AGENT = "CardPirateAtlas-yuyutei-display-evidence/1.0"


def emit(line: str = "") -> None:
    print(line, flush=True)


@dataclass
class AssetCheck:
    """Every verification result for one asset, and why it failed."""

    card_print_id: int
    checks: dict[str, bool]
    failures: list[str]

    @property
    def ok(self) -> bool:
        return not self.failures


def _public_get(url: str) -> tuple[bytes, str | None, str | None]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=PUBLIC_FETCH_TIMEOUT_SECONDS) as response:
        return (
            response.read(),
            response.headers.get("Content-Type"),
            response.headers.get("Cache-Control"),
        )


def verify_asset(asset: VerifiedYuyuteiAsset, storage: R2ObjectStorage) -> AssetCheck:
    """Re-prove the object in R2 is the one this evidence describes.

    Deliberately re-derives the object key from the digest with the shared
    helper rather than trusting the manifest's copy of it: a reader and a
    writer that disagree about the key point at an object that is not there.
    """
    checks: dict[str, bool] = {}
    extension = asset.object_key.rsplit(".", 1)[-1]

    checks["extension_known"] = extension in OBJECT_KEY_MEDIA_TYPES
    checks["content_type_matches_extension"] = (
        checks["extension_known"] and OBJECT_KEY_MEDIA_TYPES[extension] == asset.content_type
    )
    checks["object_key_derives_from_digest"] = asset.object_key == object_key(
        asset.sha256, extension
    )

    head = storage.head_object(asset.object_key)
    checks["object_exists"] = head is not None
    checks["head_content_type"] = bool(head and head.content_type == asset.content_type)
    checks["head_cache_control"] = bool(head and head.cache_control == asset.cache_control)
    checks["head_byte_size"] = bool(head and head.content_length == asset.byte_size)

    if head is not None:
        private = storage.get_object_bytes(asset.object_key)
        checks["private_digest"] = hashlib.sha256(private).hexdigest() == asset.sha256
        checks["private_byte_size"] = len(private) == asset.byte_size

        public, public_type, public_cache = _public_get(storage.public_url(asset.object_key))
        checks["public_digest"] = hashlib.sha256(public).hexdigest() == asset.sha256
        checks["public_content_type"] = (
            (public_type or "").split(";")[0].strip() == asset.content_type
        )
        checks["public_cache_control"] = public_cache == asset.cache_control

        image = Image.open(io.BytesIO(public))
        checks["public_decodes_to_manifest_size"] = image.size == (asset.width, asset.height)

    return AssetCheck(
        card_print_id=asset.card_print_id,
        checks=checks,
        failures=[name for name, passed in checks.items() if not passed],
    )


def load_manifest(path: Path) -> list[VerifiedYuyuteiAsset]:
    document = json.loads(path.read_text())
    return [
        VerifiedYuyuteiAsset(
            card_print_id=entry["card_print_id"],
            mapping_id=entry["mapping_id"],
            source_url=entry["source_url"],
            sha256=entry["sha256"],
            byte_size=entry["byte_size"],
            width=entry["width"],
            height=entry["height"],
            content_type=entry["content_type"],
            cache_control=entry["cache_control"],
            object_key=entry["object_key"],
        )
        for entry in document["assets"]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="verify every asset and report; write nothing",
    )
    mode.add_argument(
        "--persist",
        action="store_true",
        help="verify, then record display_image on each verified mapping",
    )
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

    verified: list[VerifiedYuyuteiAsset] = []
    failed = 0
    for asset in assets:
        result = verify_asset(asset, storage)
        if result.ok:
            verified.append(asset)
            emit(f"  print {asset.card_print_id:>2}  VERIFY PASS  {asset.object_key}")
        else:
            failed += 1
            emit(
                f"  print {asset.card_print_id:>2}  VERIFY FAIL  "
                f"{', '.join(result.failures)}"
            )

    emit()
    emit(f"verified {len(verified)}/{len(assets)}, failed {failed}")

    if not args.persist:
        emit("\ndry run - nothing was written to the database.")
        sys.exit(EXIT_OK if failed == 0 else EXIT_FAILED)

    if failed:
        emit("\nverification did not pass for every asset - nothing will be written.")
        sys.exit(EXIT_FAILED)

    emit()
    written = already = aborted = 0
    db: Session = SessionLocal()
    try:
        for asset in verified:
            outcome = persist_display_image(db, asset)
            if outcome.written:
                written += 1
                state = "WRITTEN"
            elif outcome.already_recorded:
                already += 1
                state = "ALREADY RECORDED (no-op)"
            else:
                aborted += 1
                state = f"ABORTED - {outcome.abort_reason}"
            emit(f"  print {asset.card_print_id:>2}  mapping {asset.mapping_id:>2}  {state}")
    finally:
        db.rollback()
        db.close()

    emit()
    emit(f"written {written}, already recorded {already}, aborted {aborted}")
    sys.exit(EXIT_OK if aborted == 0 else EXIT_FAILED)


if __name__ == "__main__":
    main()
