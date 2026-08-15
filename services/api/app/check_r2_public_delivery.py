"""CLI: prove the R2 bucket is readable over its *public* delivery origin.

    python -m app.check_r2_public_delivery

The roundtrip command (app.check_r2_roundtrip) proved that bytes survive a
PUT -> HEAD -> GET through the authenticated S3 API. That says nothing about
whether a browser can read them: public delivery goes through an entirely
different host (an r2.dev subdomain or a custom domain, configured as
R2_PUBLIC_BASE_URL), served by a different system, and can be switched off
while the S3 API keeps working perfectly. This command closes that gap and
nothing else.

It reads the object the roundtrip command already wrote:

    system-checks/r2-roundtrip-probe.txt

and compares two reads of it:

    public   an ordinary unauthenticated HTTPS GET of public_url(key)
    private  the authenticated S3 GetObject, via get_object_bytes(key)

A pass means those two reads returned the same bytes, so the public origin is
serving this bucket's real content - not a cached placeholder, not an error
page with a 200, and not some other object.

Strictly read-only. This module contains no put, no delete and no list; it
creates nothing, overwrites nothing and touches no database row. If the probe
object is missing, that is a failure to report, not something to write.

What makes the public read *public*
-----------------------------------
The GET is made with a plain httpx client carrying no auth, no cookies and no
S3 signature, and with trust_env=False so an ambient HTTPS_PROXY, NETRC or
similar cannot quietly attach a credential either. The headers actually sent
are then inspected and any credential-bearing header fails the check - the
claim "this was unauthenticated" is verified against the real request, not
asserted from the code's intent.

Because the two reads travel different paths, a mismatch is informative
rather than merely a failure: same length and different bytes points at
something transforming the response; a 200 with a different length usually
means an interstitial or error page; 403/404 mean public access is not
actually enabled for this bucket, or R2_PUBLIC_BASE_URL points somewhere
else.

Credential safety: no R2_ACCESS_KEY_ID or R2_SECRET_ACCESS_KEY value is
printed - botocore error strings are reduced to their structured fields and
everything emitted goes through the same scrub() the other two R2 commands
use. The public hostname *is* printed: it is a public delivery origin, not a
secret, and a check of public reachability that hides which host answered
proves nothing.

Explicitly out of scope: no card image, no display-image key, no database, no
upload, no delete, and no change to R2ObjectStorage.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from botocore.exceptions import BotoCoreError, ClientError

from app.check_r2_connectivity import scrub
from app.check_r2_roundtrip import PROBE_KEY, PROBE_KEY_PREFIX
from app.services.object_storage import R2ConfigurationError, R2ObjectStorage

# Fixed and explicit rather than left to httpx's defaults, so a later
# dependency bump cannot silently change what this check sends.
FETCH_TIMEOUT_SECONDS = 20.0
USER_AGENT = "CardPirateAtlas-r2-public-delivery-check/1.0"

# Any of these on the outgoing request would mean the read was not public.
# Matched case-insensitively. "cookie" is here because a session cookie is a
# credential too, even though nothing in this module sets one.
CREDENTIAL_HEADERS = (
    "authorization",
    "cookie",
    "proxy-authorization",
    "x-amz-content-sha256",
    "x-amz-date",
    "x-amz-security-token",
)

# The S3 API host. A public base URL pointing at it would make a passing
# fetch meaningless - that is the authenticated path wearing a different
# name, not public delivery.
S3_API_HOST_SUFFIX = "r2.cloudflarestorage.com"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NOT_CONFIGURED = 2


# --- the public fetch -------------------------------------------------------


@dataclass(frozen=True)
class PublicFetch:
    """One unauthenticated HTTP GET, and the evidence that it was one."""

    http_status: int
    final_url: str
    final_host: str | None
    redirected: bool
    content_type: str | None
    body: bytes
    request_headers: dict[str, str]

    @property
    def credential_headers_sent(self) -> list[str]:
        return sorted(
            name for name in self.request_headers if name.lower() in CREDENTIAL_HEADERS
        )


def fetch_public_url(url: str, *, transport: httpx.BaseTransport | None = None) -> PublicFetch:
    """GET `url` as an anonymous client would, once, and record what was sent.

    auth=None and trust_env=False together are the whole point: no explicit
    credential, and no ambient one picked up from the environment (proxy
    auth, ~/.netrc). Redirects are followed but reported, because a public
    origin that redirects elsewhere is worth seeing even when the bytes
    ultimately match.

    `transport` exists so tests can drive this exact function - the real
    client, real headers, real settings - against httpx.MockTransport instead
    of the network.
    """
    with httpx.Client(
        follow_redirects=True,
        timeout=FETCH_TIMEOUT_SECONDS,
        trust_env=False,
        auth=None,
        transport=transport,
    ) as client:
        response = client.get(url, headers={"User-Agent": USER_AGENT})
    return PublicFetch(
        http_status=response.status_code,
        final_url=str(response.url),
        final_host=urlparse(str(response.url)).hostname,
        redirected=bool(response.history),
        content_type=response.headers.get("content-type"),
        body=response.content,
        request_headers=dict(response.request.headers),
    )


# --- result -----------------------------------------------------------------


@dataclass
class Stage:
    name: str
    ok: bool
    detail: str


STAGE_COUNT = 4


@dataclass
class PublicDeliveryResult:
    stages: list[Stage] = field(default_factory=list)
    public_url: str | None = None
    public_host: str | None = None
    http_status: int | None = None
    public_byte_length: int | None = None
    private_byte_length: int | None = None
    public_sha256: str | None = None
    private_sha256: str | None = None
    unauthenticated: bool | None = None

    @property
    def failed_stage(self) -> str | None:
        for stage in self.stages:
            if not stage.ok:
                return stage.name
        return None

    @property
    def ok(self) -> bool:
        return self.failed_stage is None and len(self.stages) == STAGE_COUNT

    @property
    def exit_code(self) -> int:
        return EXIT_OK if self.ok else EXIT_FAILED

    def record(self, name: str, ok: bool, detail: str) -> bool:
        self.stages.append(Stage(name=name, ok=ok, detail=detail))
        return ok


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


def explain_status(status: int) -> str:
    """What a non-200 from the public origin most likely means."""
    if status == 403:
        return (
            "403 - the public origin refused the request. Public access (r2.dev) is "
            "most likely not enabled for this bucket, or a custom domain is not bound "
            "to it. The object itself is unaffected."
        )
    if status == 404:
        return (
            "404 - the public origin answered but has no object at this key. Either "
            "R2_PUBLIC_BASE_URL points at a different bucket, or the probe object is "
            "missing from the bucket this base URL serves."
        )
    if 500 <= status < 600:
        return f"{status} - the public origin failed to serve the object; this is a server-side error."
    return f"{status} - unexpected status from the public origin; only 200 is a pass."


# --- the check --------------------------------------------------------------


def run_public_delivery_check(
    storage: R2ObjectStorage,
    *,
    key: str = PROBE_KEY,
    fetcher=None,
) -> PublicDeliveryResult:
    """origin -> public GET -> private GET -> compare. Stops at the first failure.

    `fetcher` is looked up at call time rather than bound as a default, so a
    test that replaces the module's fetch_public_url is actually honoured.
    """
    fetcher = fetcher if fetcher is not None else fetch_public_url
    if not key.startswith(PROBE_KEY_PREFIX):
        raise ValueError(
            f"Public delivery check key must live under {PROBE_KEY_PREFIX!r}, got {key!r}"
        )

    result = PublicDeliveryResult()
    result.public_url = storage.public_url(key)
    result.public_host = urlparse(result.public_url).hostname

    # --- origin ------------------------------------------------------------
    host = result.public_host or ""
    if host == S3_API_HOST_SUFFIX or host.endswith("." + S3_API_HOST_SUFFIX):
        result.record(
            "origin",
            False,
            f"R2_PUBLIC_BASE_URL resolves to the S3 API host ({host}); that is the "
            "authenticated endpoint, not a public delivery origin, so a fetch through "
            "it would prove nothing about public access.",
        )
        return result
    result.record("origin", True, f"public delivery host is {host} (not the S3 API host)")

    # --- public ------------------------------------------------------------
    try:
        fetched = fetcher(result.public_url)
    except httpx.HTTPError as exc:
        result.record(
            "public",
            False,
            f"the unauthenticated GET never completed: {type(exc).__name__}",
        )
        return result

    result.http_status = fetched.http_status
    result.public_byte_length = len(fetched.body)
    result.public_sha256 = hashlib.sha256(fetched.body).hexdigest()

    leaked = fetched.credential_headers_sent
    result.unauthenticated = not leaked
    if leaked:
        # Not a delivery failure - a failure of this command's own guarantee.
        # Reporting a pass here would assert something untrue.
        result.record(
            "public",
            False,
            f"the request carried credential header(s) {leaked} and was therefore not "
            "an unauthenticated read; nothing about public delivery is proven.",
        )
        return result

    if fetched.http_status != 200:
        result.record("public", False, explain_status(fetched.http_status))
        return result
    if not fetched.body:
        result.record(
            "public",
            False,
            "200 with an empty body - the public origin answered but served no bytes.",
        )
        return result
    redirect_note = f", after a redirect to {fetched.final_host}" if fetched.redirected else ""
    result.record(
        "public",
        True,
        f"HTTP 200, {len(fetched.body)} bytes, content_type="
        f"{fetched.content_type!r}, unauthenticated{redirect_note}",
    )

    # --- private -----------------------------------------------------------
    try:
        private_bytes = storage.get_object_bytes(key)
    except (ClientError, BotoCoreError) as exc:
        detail = (
            describe_client_error(exc) if isinstance(exc, ClientError) else type(exc).__name__
        )
        result.record("private", False, f"GetObject failed: {detail}")
        return result
    result.private_byte_length = len(private_bytes)
    result.private_sha256 = hashlib.sha256(private_bytes).hexdigest()
    result.record("private", True, f"authenticated GetObject read {len(private_bytes)} bytes")

    # --- compare -----------------------------------------------------------
    if result.public_byte_length != result.private_byte_length:
        result.record(
            "compare",
            False,
            f"byte length mismatch: public {result.public_byte_length}, "
            f"private {result.private_byte_length}",
        )
        return result
    if result.public_sha256 != result.private_sha256:
        result.record(
            "compare",
            False,
            f"SHA-256 mismatch: public {result.public_sha256}, private {result.private_sha256}",
        )
        return result
    if fetched.body != private_bytes:
        # Belt and braces: equal digests but unequal bytes would mean a
        # collision or a bug here, either of which must fail.
        result.record("compare", False, "digests agree but the raw bytes differ")
        return result
    result.record(
        "compare",
        True,
        f"public and private bytes are identical ({result.public_byte_length} bytes, "
        f"sha256={result.public_sha256})",
    )
    return result


# --- output -----------------------------------------------------------------


def emit(line: str = "") -> None:
    print(scrub(line))


def print_result(result: PublicDeliveryResult, key: str, storage: R2ObjectStorage) -> None:
    emit("R2 public delivery smoke test")
    emit(f"  bucket       : {storage.bucket_name}")
    emit(f"  key          : {key}")
    emit(f"  public host  : {result.public_host}")
    emit(f"  public url   : {result.public_url}")
    emit(f"  s3 api host  : *.{S3_API_HOST_SUFFIX} (a different host, used only for "
         "the authenticated read)")
    emit()
    for stage in result.stages:
        emit(f"  [{'OK' if stage.ok else 'FAIL'}] {stage.name:<8}{stage.detail}")
    emit()
    emit(f"  public   : status={result.http_status} {result.public_byte_length} bytes  "
         f"sha256={result.public_sha256}")
    emit(f"  private  : {result.private_byte_length} bytes  sha256={result.private_sha256}")
    if result.unauthenticated is None:
        emit("  auth sent: n/a - the public GET was never made")
    elif result.unauthenticated:
        emit("  auth sent: none (no Authorization, cookie or S3 signature headers)")
    else:
        emit("  auth sent: CREDENTIAL HEADERS PRESENT - see the failure above")
    emit()
    if result.ok:
        emit("[OK] the public origin serves this bucket's real bytes, byte-for-byte, "
             "to an unauthenticated client.")
    else:
        emit(f"[FAIL] public delivery check failed at stage: {result.failed_stage}")
    emit(
        "read-only: nothing was uploaded, overwritten or deleted, and no card image, "
        "display-image key or database row was involved."
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch the existing system-checks probe object over the public "
            "R2_PUBLIC_BASE_URL origin with an unauthenticated GET, and prove the "
            "bytes match the authenticated S3 read exactly. Writes nothing."
        )
    )
    # Deliberately no --key: the only object this may read is the probe the
    # roundtrip command already wrote.
    parser.parse_args(argv)

    try:
        storage = R2ObjectStorage.from_settings()
    except R2ConfigurationError as exc:
        emit(f"[FAIL] not configured: {scrub(str(exc))}")
        sys.exit(EXIT_NOT_CONFIGURED)

    result = run_public_delivery_check(storage)
    print_result(result, PROBE_KEY, storage)
    sys.exit(result.exit_code)


if __name__ == "__main__":
    main()
