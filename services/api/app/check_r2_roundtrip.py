"""CLI: prove a real PUT -> HEAD -> GET roundtrip against R2 with throwaway bytes.

    python -m app.check_r2_roundtrip

The first command in this repository that writes to object storage. It writes
one small text file and nothing else, at a fixed key under system-checks/:

    system-checks/r2-roundtrip-probe.txt

Why the key is fixed and not configurable: R2ObjectStorage has no delete (by
design - nothing in the mirroring plan needs one), so anything this command
creates is permanent. A fixed key means repeated runs overwrite that single
object instead of littering the bucket, and there is deliberately no --key
flag, so no invocation of this command can reach a display-image key or any
other production object.

Why the payload is not fixed: it embeds this run's UTC timestamp and a random
nonce. A constant payload would still pass every check by reading back an
object a *previous* run left behind - the write itself would go unverified.
Fresh bytes each run mean the GET can only match if this run's PUT actually
landed.

The four stages, each of which must pass before the next is attempted:

    put     put_object with ContentType=text/plain, CacheControl=no-store
    head    the object exists, with the exact byte length and content type
    get     the bytes come back
    verify  SHA-256 of what was sent == SHA-256 of what came back

Any failure exits non-zero naming the stage that failed. Exit 0 means all
four passed.

Explicitly out of scope: the public r2.dev delivery URL is not requested, no
card image or display-image byte is involved, no database is touched, and no
delete is performed or added.

Credential safety: no R2_ACCESS_KEY_ID or R2_SECRET_ACCESS_KEY value is ever
printed. As in app.check_r2_connectivity, botocore error strings are never
printed raw - only the structured Code, HTTP status and operation - and the
same scrub() is applied to everything emitted.
"""

from __future__ import annotations

import hashlib
import secrets
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from botocore.exceptions import BotoCoreError, ClientError

from app.check_r2_connectivity import scrub
from app.services.object_storage import R2ConfigurationError, R2ObjectStorage

# Fixed, and under system-checks/ so it can never collide with a display
# image. Overwritten in place by every run - there is no delete to clean up
# with, so one object is the most this command may ever create.
PROBE_KEY_PREFIX = "system-checks/"
PROBE_KEY = "system-checks/r2-roundtrip-probe.txt"

CONTENT_TYPE = "text/plain"
# no-store, not the immutable policy display images will use: this object is
# rewritten on every run, so it must never be cached anywhere.
CACHE_CONTROL = "no-store"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NOT_CONFIGURED = 2


@dataclass
class Stage:
    name: str
    ok: bool
    detail: str


@dataclass
class RoundtripResult:
    stages: list[Stage] = field(default_factory=list)
    sent_sha256: str | None = None
    returned_sha256: str | None = None
    sent_bytes: int | None = None
    returned_bytes: int | None = None

    @property
    def failed_stage(self) -> str | None:
        for stage in self.stages:
            if not stage.ok:
                return stage.name
        return None

    @property
    def ok(self) -> bool:
        return self.failed_stage is None and len(self.stages) == 4

    @property
    def exit_code(self) -> int:
        return EXIT_OK if self.ok else EXIT_FAILED

    def record(self, name: str, ok: bool, detail: str) -> bool:
        self.stages.append(Stage(name=name, ok=ok, detail=detail))
        return ok


def build_payload() -> bytes:
    """Unique per run, so a passing GET can only mean this run's PUT landed."""
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    nonce = secrets.token_hex(8)
    return (
        "cardpirate-atlas r2 roundtrip probe\n"
        f"written_at={stamp}\n"
        f"nonce={nonce}\n"
        "This object is a storage self-test. It contains no card data and is "
        "safe to delete.\n"
    ).encode("utf-8")


def describe_client_error(exc: ClientError) -> str:
    """Structured fields only - botocore's message text can quote credentials."""
    response = exc.response or {}
    error = response.get("Error") or {}
    metadata = response.get("ResponseMetadata") or {}
    return (
        f"Code={error.get('Code')!r} "
        f"HTTP={metadata.get('HTTPStatusCode')} "
        f"operation={getattr(exc, 'operation_name', None)!r}"
    )


def run_roundtrip(
    storage: R2ObjectStorage, payload: bytes, key: str = PROBE_KEY
) -> RoundtripResult:
    """PUT, HEAD, GET, compare. Stops at the first failing stage."""
    if not key.startswith(PROBE_KEY_PREFIX):
        raise ValueError(
            f"Roundtrip probe key must live under {PROBE_KEY_PREFIX!r}, got {key!r}"
        )

    result = RoundtripResult()
    result.sent_bytes = len(payload)
    result.sent_sha256 = hashlib.sha256(payload).hexdigest()

    # --- put ---------------------------------------------------------------
    try:
        storage.put_object(
            key,
            payload,
            content_type=CONTENT_TYPE,
            cache_control=CACHE_CONTROL,
        )
    except (ClientError, BotoCoreError) as exc:
        detail = (
            describe_client_error(exc)
            if isinstance(exc, ClientError)
            else type(exc).__name__
        )
        result.record("put", False, f"PutObject failed: {detail}")
        return result
    result.record("put", True, f"wrote {len(payload)} bytes to {key}")

    # --- head --------------------------------------------------------------
    try:
        head = storage.head_object(key)
    except (ClientError, BotoCoreError) as exc:
        detail = (
            describe_client_error(exc)
            if isinstance(exc, ClientError)
            else type(exc).__name__
        )
        result.record("head", False, f"HeadObject failed: {detail}")
        return result

    if head is None:
        result.record(
            "head", False, "HeadObject reported not-found immediately after a successful PUT"
        )
        return result
    if head.content_length != len(payload):
        result.record(
            "head",
            False,
            f"content length mismatch: sent {len(payload)}, HEAD reports {head.content_length}",
        )
        return result
    if head.content_type != CONTENT_TYPE:
        result.record(
            "head",
            False,
            f"content type mismatch: sent {CONTENT_TYPE!r}, HEAD reports {head.content_type!r}",
        )
        return result
    result.record(
        "head",
        True,
        f"exists, content_length={head.content_length}, content_type={head.content_type!r}, "
        f"cache_control={head.cache_control!r}, etag={head.etag!r} (opaque)",
    )

    # --- get ---------------------------------------------------------------
    try:
        returned = storage.get_object_bytes(key)
    except (ClientError, BotoCoreError) as exc:
        detail = (
            describe_client_error(exc)
            if isinstance(exc, ClientError)
            else type(exc).__name__
        )
        result.record("get", False, f"GetObject failed: {detail}")
        return result
    result.returned_bytes = len(returned)
    result.returned_sha256 = hashlib.sha256(returned).hexdigest()
    result.record("get", True, f"read back {len(returned)} bytes")

    # --- verify ------------------------------------------------------------
    if result.returned_sha256 != result.sent_sha256:
        result.record(
            "verify",
            False,
            f"SHA-256 mismatch: sent {result.sent_sha256}, returned {result.returned_sha256}",
        )
        return result
    if returned != payload:
        # Belt and braces: equal digests but unequal bytes would mean a
        # collision or a bug in this command, either of which must fail.
        result.record("verify", False, "digests agree but the bytes differ")
        return result
    result.record("verify", True, f"SHA-256 matches exactly: {result.sent_sha256}")
    return result


def print_result(result: RoundtripResult, key: str, storage: R2ObjectStorage) -> None:
    print(scrub("R2 write roundtrip smoke test"))
    print(scrub(f"  bucket    : {storage.bucket_name}"))
    print(scrub(f"  key       : {key}"))
    print(scrub(f"  content   : {CONTENT_TYPE}, CacheControl={CACHE_CONTROL}"))
    print()
    for stage in result.stages:
        print(scrub(f"  [{'OK' if stage.ok else 'FAIL'}] {stage.name:<7}{stage.detail}"))
    print()
    print(scrub(f"  sent     : {result.sent_bytes} bytes  sha256={result.sent_sha256}"))
    print(
        scrub(
            f"  returned : {result.returned_bytes} bytes  sha256={result.returned_sha256}"
        )
    )
    print()
    if result.ok:
        print(scrub("[OK] real PUT -> HEAD -> GET roundtrip verified byte-for-byte."))
    else:
        print(scrub(f"[FAIL] roundtrip failed at stage: {result.failed_stage}"))
    print(
        scrub(
            "no card image, no database row and no display-image evidence was involved; "
            "nothing was deleted."
        )
    )


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Write a tiny throwaway text object to R2, read it back, and verify "
            "the bytes survive exactly. Uses a fixed key under system-checks/; "
            "no card data is involved and nothing is deleted."
        )
    )
    # Deliberately no --key: see the module docstring.
    parser.parse_args(argv)

    try:
        storage = R2ObjectStorage.from_settings()
    except R2ConfigurationError as exc:
        print(scrub(f"[FAIL] not configured: {exc}"))
        sys.exit(EXIT_NOT_CONFIGURED)

    result = run_roundtrip(storage, build_payload())
    print_result(result, PROBE_KEY, storage)
    sys.exit(result.exit_code)


if __name__ == "__main__":
    main()
