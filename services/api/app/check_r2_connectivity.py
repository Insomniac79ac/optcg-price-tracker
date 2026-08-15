"""CLI: prove the configured R2 credentials work, without touching a byte.

    python -m app.check_r2_connectivity

One HeadObject against a key that is meant not to exist:

    system-checks/r2-read-probe-does-not-exist

A "404 not found" is the *success* case. Reaching that answer means the
account id resolved, TLS and the S3 signature were accepted, the token is
scoped to this bucket and the bucket exists - everything the mirroring
tranche needs, established without creating, modifying, listing or reading a
single object. The command calls exactly one method on R2ObjectStorage
(head_object); put_object, get_object_bytes and any list/delete operation are
absent from this module and must stay absent.

Exit codes:

    0  HeadObject executed and reported not-found - credentials verified
    1  storage or connection failure (403, wrong bucket, wrong endpoint, ...)
    1  the probe key unexpectedly EXISTS - see below
    2  R2 is not configured (or is misconfigured) in this environment

The probe key existing is treated as a failure, not a success. Authentication
demonstrably worked in that case, but the key's entire purpose is to be
absent: something has written to it, which means either the bucket is not the
one intended or this repo's read-only guarantee has been broken somewhere.
That deserves a non-zero exit and a human, not a green tick.

Credential safety: no value of R2_ACCESS_KEY_ID or R2_SECRET_ACCESS_KEY is
ever printed. botocore's own error strings can quote the access key id back
(S3's InvalidAccessKeyId response body contains it), so this module never
prints str(exception) - only the structured Code, HTTP status and operation
name - and additionally scrubs both credentials out of everything it emits
as a second line of defence.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from botocore.exceptions import BotoCoreError, ClientError

from app.services.object_storage import (
    R2_ENDPOINT_TEMPLATE,
    R2ConfigurationError,
    R2ObjectStorage,
)
from app.settings import settings

# Deliberately descriptive: anyone who finds this key in a bucket listing or
# an access log should immediately understand what it is and that nothing is
# supposed to be stored under it.
PROBE_KEY = "system-checks/r2-read-probe-does-not-exist"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NOT_CONFIGURED = 2


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of the single HeadObject call, in a form tests can assert on."""

    outcome: str  # not_found | unexpectedly_present | storage_error | connection_error
    exit_code: int
    detail: str
    error_code: str | None = None
    http_status: int | None = None
    operation: str | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == EXIT_OK


def scrub(text: str) -> str:
    """Remove either credential from `text`, should one ever reach it.

    Nothing in this module deliberately puts a credential into a string; this
    exists because botocore's error messages are outside our control and a
    leaked key in a terminal transcript or CI log cannot be un-leaked.
    """
    for secret in (settings.R2_ACCESS_KEY_ID, settings.R2_SECRET_ACCESS_KEY):
        if secret and secret.strip():
            text = text.replace(secret.strip(), "<redacted>")
    return text


def emit(line: str = "") -> None:
    print(scrub(line))


def probe(storage: R2ObjectStorage, key: str = PROBE_KEY) -> ProbeResult:
    """The whole test: one HeadObject, and an opinion about what came back."""
    try:
        head = storage.head_object(key)
    except ClientError as exc:
        response = exc.response or {}
        error = response.get("Error") or {}
        metadata = response.get("ResponseMetadata") or {}
        code = str(error.get("Code", "")) or None
        status = metadata.get("HTTPStatusCode")
        operation = getattr(exc, "operation_name", None)
        return ProbeResult(
            outcome="storage_error",
            exit_code=EXIT_FAILED,
            detail=(
                "HeadObject was rejected. A 403/InvalidAccessKeyId/"
                "SignatureDoesNotMatch means the token or its scope is wrong; "
                "a 404 NoSuchBucket means the bucket name is wrong."
            ),
            error_code=code,
            http_status=status if isinstance(status, int) else None,
            operation=operation,
        )
    except BotoCoreError as exc:
        # Endpoint unresolvable, TLS failure, connection refused - i.e. the
        # request never reached a bucket at all.
        return ProbeResult(
            outcome="connection_error",
            exit_code=EXIT_FAILED,
            detail=(
                "The request never reached R2. Check R2_ACCOUNT_ID and outbound "
                "network access from this environment."
            ),
            error_code=type(exc).__name__,
        )

    if head is None:
        return ProbeResult(
            outcome="not_found",
            exit_code=EXIT_OK,
            detail=(
                "HeadObject executed and reported not-found. Authentication, "
                "endpoint, signing, token scope and bucket are all confirmed."
            ),
        )

    return ProbeResult(
        outcome="unexpectedly_present",
        exit_code=EXIT_FAILED,
        detail=(
            f"The probe key EXISTS ({head.content_length} bytes, "
            f"content_type={head.content_type!r}). Authentication worked, but this "
            "key is supposed to be absent - either this is not the intended "
            "bucket, or something has written to it. Nothing was read or "
            "modified; investigate before trusting this bucket."
        ),
    )


def print_context(storage: R2ObjectStorage, key: str) -> None:
    """Everything needed to diagnose a failure, and nothing secret. The account
    id appears only inside the endpoint host, which is what makes a
    wrong-endpoint failure legible."""
    emit("R2 read-only connectivity probe")
    emit(f"  endpoint     : {R2_ENDPOINT_TEMPLATE.format(account_id=settings.R2_ACCOUNT_ID)}")
    emit(f"  bucket       : {storage.bucket_name}")
    emit(f"  public origin: {storage.public_base_url}")
    emit(f"  probe key    : {key}")
    emit("  operation    : HeadObject (read-only; no PUT, GET, LIST or DELETE)")
    emit()


def print_result(result: ProbeResult) -> None:
    label = "OK" if result.ok else "FAIL"
    emit(f"[{label}] {result.outcome}")
    if result.error_code:
        emit(f"  error code   : {result.error_code}")
    if result.http_status is not None:
        emit(f"  http status  : {result.http_status}")
    if result.operation:
        emit(f"  operation    : {result.operation}")
    emit(f"  {result.detail}")
    emit()
    emit("nothing was uploaded, modified, deleted or read: this command issues "
         "exactly one HeadObject.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the configured Cloudflare R2 credentials with a single "
            "read-only HeadObject against a key that should not exist. Creates, "
            "modifies and reads nothing."
        )
    )
    parser.add_argument(
        "--key",
        default=PROBE_KEY,
        help=f"Object key to HEAD (read-only). Default: {PROBE_KEY}",
    )
    args = parser.parse_args(argv)

    try:
        storage = R2ObjectStorage.from_settings()
    except R2ConfigurationError as exc:
        # The message names the missing setting and never carries a value.
        emit(f"[FAIL] not configured: {scrub(str(exc))}")
        sys.exit(EXIT_NOT_CONFIGURED)

    print_context(storage, args.key)
    result = probe(storage, args.key)
    print_result(result)
    sys.exit(result.exit_code)


if __name__ == "__main__":
    main()
