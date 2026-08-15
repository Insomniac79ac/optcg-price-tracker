"""Upload half of the display-image mirroring pipeline: one verified asset,
one content-addressed R2 object, verified back through both doors.

The verification half (app.services.display_image_mirror) proves an asset
still matches its retained evidence. The storage half
(app.services.object_storage) moves exact bytes to an exact key. This module
is the join between them, and adds only what neither can know alone: *the
same bytes must come back out, over the authenticated S3 API and over the
public delivery origin, and still decode to the geometry the frontend guard
expects.*

Nothing here is card-aware beyond selecting the print it was asked for, and
nothing here is storage-aware beyond the four operations R2ObjectStorage
exposes. Both halves are imported, never re-implemented - a second copy of
the eligibility predicate or of the key format is exactly the kind of drift
that would let an unverified asset reach a key some other asset owns.

Identity is the stored full digest, not the prefix
--------------------------------------------------
`display_image.fetch.sha256` (64 hex, persisted 2026-08-14) is authoritative
here. The 16-hex `sha256_prefix` retained in 2026-08-13 is 64 bits: fine as
the drift signal it was introduced to be, useless as the identity of an
object whose *key is its digest*. So this module requires the stored full
digest to exist and to equal the digest computed from the bytes fetched in
this same run, and refuses to upload anything otherwise. It never falls back
to the prefix, and it never derives the key from a digest that has not been
confirmed against both the stored evidence and the live bytes.

An asset that has not been bootstrapped yet is not a soft skip - it is a
failure. Uploading it would mean content-addressing an object by a digest no
stored evidence has ever agreed with.

Byte discipline
---------------
Exactly one authoritative buffer, the HTTP response body produced by the
verification phase. It is what is hashed, what is PUT, and what every later
comparison is made against. Nothing in this module resizes, crops,
re-encodes, converts, flattens alpha or calls Image.save; Pillow appears
once, to *decode* the bytes that came back from the public origin so their
natural dimensions can be checked. That decode produces no bytes that are
stored, returned or compared as bytes.

Writes, and what is deliberately absent
---------------------------------------
The only write this module can perform is a single PutObject, to a key that
is the SHA-256 of the bytes being written, and only when HEAD says nothing is
there. An object that already exists is never overwritten - under a
content-addressed key an existing object is either identical (so writing it
again is pointless) or a contradiction (so writing over it destroys
evidence). Either way the answer is to verify, not to PUT.

There is no database write of any kind. No owned_asset row, no
match_explanation_json edit, no card_prints.image_url or artwork_key change.
The session is used read-only, by the verification phase, and a final check
asserts it holds nothing pending. Making the mirrored URL *visible* - to
GET /prints or to the frontend - is a separate tranche and is not started
here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from urllib.parse import urlparse

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.orm import Session

from app.check_r2_public_delivery import fetch_public_url
from app.services.display_image_mirror import (
    AssetVerification,
    Fetcher,
    fetch_image,
    inspect_image,
    object_key,
    run_verification,
)
from app.services.object_storage import R2ObjectStorage

# The one source whose display images this tranche may mirror. The verifier's
# own selection is broader (any source in DISPLAY_SOURCE_PRIORITY); this is a
# second, explicit gate so widening that list cannot silently widen what gets
# uploaded.
ALLOWED_SOURCE = "snkrdunk"

# Decoded format and media type, stated rather than inferred. Every approved
# display asset is WEBP; a PNG or JPEG arriving here would mean the CDN
# changed what it serves, which is a finding, not something to accommodate.
REQUIRED_IMAGE_FORMAT = "WEBP"
REQUIRED_MEDIA_TYPE = "image/webp"
REQUIRED_EXTENSION = "webp"

CONTENT_TYPE = REQUIRED_MEDIA_TYPE
# A year, immutable - safe precisely because the key is the content digest,
# so the bytes under it can never change. The opposite of the roundtrip
# probe's no-store, and the reason that probe must never share this policy.
CACHE_CONTROL = "public, max-age=31536000, immutable"


@dataclass
class Stage:
    name: str
    ok: bool
    detail: str


STAGE_NAMES = ("verify", "digest", "key", "head", "upload", "private", "public", "db")


@dataclass
class MirrorOutcome:
    """Everything one mirrored asset did, whether it passed or not."""

    card_print_id: int
    stages: list[Stage] = field(default_factory=list)
    mapping_id: int | None = None
    source_url: str | None = None
    stored_sha256: str | None = None
    computed_sha256: str | None = None
    source_byte_length: int | None = None
    object_key: str | None = None
    # None until the head stage runs; True = this run PUT the object,
    # False = it was already there and was left alone.
    uploaded: bool | None = None
    private_byte_length: int | None = None
    private_sha256: str | None = None
    head_content_type: str | None = None
    head_cache_control: str | None = None
    head_content_length: int | None = None
    public_url: str | None = None
    public_host: str | None = None
    public_status: int | None = None
    public_byte_length: int | None = None
    public_sha256: str | None = None
    public_dimensions: tuple[int, int] | None = None
    expected_canvas_px: tuple[int, int] | None = None
    verification: AssetVerification | None = None

    @property
    def failed_stage(self) -> str | None:
        for stage in self.stages:
            if not stage.ok:
                return stage.name
        return None

    @property
    def ok(self) -> bool:
        return self.failed_stage is None and len(self.stages) == len(STAGE_NAMES)

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

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


def _storage_failure(exc: Exception) -> str:
    return describe_client_error(exc) if isinstance(exc, ClientError) else type(exc).__name__


def mirror_print(
    db: Session,
    card_print_id: int,
    storage: R2ObjectStorage,
    *,
    fetcher: Fetcher = fetch_image,
    public_fetcher=None,
) -> MirrorOutcome:
    """Verify, upload if absent, then read back privately and publicly.

    Exactly one print, named explicitly - there is no "all" path in this
    function and no way for a second asset to be touched by a call. Stops at
    the first failing stage, and every stage before the upload is a gate: no
    PutObject is reachable until the asset has passed the full verifier *and*
    matched its stored full digest.
    """
    public_fetcher = public_fetcher if public_fetcher is not None else fetch_public_url
    outcome = MirrorOutcome(card_print_id=card_print_id)

    # --- verify ------------------------------------------------------------
    report = run_verification(db, card_print_ids=[card_print_id], fetcher=fetcher)
    if len(report.verifications) != 1:
        outcome.record(
            "verify",
            False,
            f"expected exactly 1 eligible display asset for print {card_print_id}, "
            f"got {len(report.verifications)}"
            + (
                f"; skipped: {[(s.mapping_id, s.reason) for s in report.skipped]}"
                if report.skipped
                else ""
            ),
        )
        return outcome

    verification = report.verifications[0]
    evidence = verification.evidence
    outcome.verification = verification
    outcome.mapping_id = evidence.mapping_id
    outcome.source_url = evidence.url
    outcome.stored_sha256 = evidence.existing_sha256
    outcome.computed_sha256 = verification.sha256
    outcome.source_byte_length = verification.actual_bytes
    outcome.expected_canvas_px = evidence.canvas_px

    if evidence.card_print_id != card_print_id:
        # Cannot happen through collect_candidates' own filter; asserted anyway
        # because uploading another print's artwork is the worst outcome here.
        outcome.record(
            "verify",
            False,
            f"selected asset belongs to print {evidence.card_print_id}, not {card_print_id}",
        )
        return outcome
    if not verification.passed:
        outcome.record(
            "verify", False, "asset failed verification: " + "; ".join(verification.failures)
        )
        return outcome
    if evidence.source != ALLOWED_SOURCE:
        outcome.record(
            "verify",
            False,
            f"source {evidence.source!r} is not {ALLOWED_SOURCE!r}",
        )
        return outcome
    if verification.image_format != REQUIRED_IMAGE_FORMAT:
        outcome.record(
            "verify",
            False,
            f"decoded format {verification.image_format!r} is not {REQUIRED_IMAGE_FORMAT}",
        )
        return outcome
    if verification.fetch is None or verification.fetch.media_type != REQUIRED_MEDIA_TYPE:
        media_type = verification.fetch.media_type if verification.fetch else None
        outcome.record(
            "verify", False, f"content type {media_type!r} is not {REQUIRED_MEDIA_TYPE!r}"
        )
        return outcome
    outcome.record(
        "verify",
        True,
        f"mapping {evidence.mapping_id}, {evidence.source}, VERIFIED_DISPLAY, "
        f"{verification.actual_bytes} bytes, {REQUIRED_IMAGE_FORMAT}, canvas "
        f"{evidence.canvas_px[0]}x{evidence.canvas_px[1]}, alpha bbox matches",
    )

    source_bytes = verification.fetch.body

    # --- digest ------------------------------------------------------------
    # The gate the whole tranche turns on. The prefix has already been checked
    # by the verifier; it is not sufficient identity for a content-addressed
    # key and is never used as a fallback here.
    if evidence.existing_sha256 is None:
        outcome.record(
            "digest",
            False,
            "no stored fetch.sha256 - this asset has not been bootstrapped, so there is "
            "no authoritative digest to content-address it by. Refusing to upload.",
        )
        return outcome
    if evidence.existing_sha256 != verification.sha256:
        outcome.record(
            "digest",
            False,
            f"stored fetch.sha256 {evidence.existing_sha256} != digest of the bytes "
            f"fetched now {verification.sha256}. The asset has changed. Refusing to upload.",
        )
        return outcome
    outcome.record(
        "digest",
        True,
        f"stored fetch.sha256 matches the live bytes exactly: {evidence.existing_sha256}",
    )

    # --- key ---------------------------------------------------------------
    key = object_key(evidence.existing_sha256, REQUIRED_EXTENSION)
    outcome.object_key = key
    outcome.public_url = storage.public_url(key)
    outcome.public_host = urlparse(outcome.public_url).hostname
    outcome.record("key", True, f"content-addressed key derived from the verified digest: {key}")

    # --- head --------------------------------------------------------------
    try:
        head = storage.head_object(key)
    except (ClientError, BotoCoreError) as exc:
        outcome.record("head", False, f"HeadObject failed: {_storage_failure(exc)}")
        return outcome

    if head is None:
        outcome.uploaded = True
        outcome.record("head", True, "object is absent - this run will upload it")
    else:
        outcome.uploaded = False
        outcome.head_content_length = head.content_length
        outcome.head_content_type = head.content_type
        outcome.head_cache_control = head.cache_control
        if head.content_length != len(source_bytes):
            # Under a content-addressed key this is a contradiction, not a
            # reason to rewrite: something else already owns this digest.
            outcome.record(
                "head",
                False,
                f"an object already exists at this key with {head.content_length} bytes, "
                f"but the verified source is {len(source_bytes)} bytes. Refusing to "
                "overwrite; investigate before mirroring anything.",
            )
            return outcome
        outcome.record(
            "head",
            True,
            f"object already exists ({head.content_length} bytes, "
            f"content_type={head.content_type!r}) - leaving it untouched",
        )

    # --- upload ------------------------------------------------------------
    if outcome.uploaded:
        try:
            storage.put_object(
                key,
                source_bytes,
                content_type=CONTENT_TYPE,
                cache_control=CACHE_CONTROL,
            )
        except (ClientError, BotoCoreError) as exc:
            outcome.record("upload", False, f"PutObject failed: {_storage_failure(exc)}")
            return outcome
        outcome.record(
            "upload",
            True,
            f"PUT {len(source_bytes)} verified bytes, ContentType={CONTENT_TYPE}, "
            f"CacheControl={CACHE_CONTROL}",
        )
    else:
        outcome.record(
            "upload", True, "skipped - the object was already present and was not overwritten"
        )

    # --- private -----------------------------------------------------------
    try:
        returned = storage.get_object_bytes(key)
    except (ClientError, BotoCoreError) as exc:
        outcome.record("private", False, f"GetObject failed: {_storage_failure(exc)}")
        return outcome
    outcome.private_byte_length = len(returned)
    outcome.private_sha256 = hashlib.sha256(returned).hexdigest()

    if outcome.private_byte_length != len(source_bytes):
        outcome.record(
            "private",
            False,
            f"byte length {outcome.private_byte_length} != verified source "
            f"{len(source_bytes)}",
        )
        return outcome
    if outcome.private_sha256 != evidence.existing_sha256:
        outcome.record(
            "private",
            False,
            f"SHA-256 {outcome.private_sha256} != stored fetch.sha256 "
            f"{evidence.existing_sha256}",
        )
        return outcome
    if returned != source_bytes:
        outcome.record("private", False, "digests agree but the raw bytes differ")
        return outcome

    # HEAD again, so the object's stored metadata is confirmed after the PUT
    # rather than assumed from what was sent. ETag is read for nobody: it is
    # an opaque server token, never an integrity check.
    try:
        head = storage.head_object(key)
    except (ClientError, BotoCoreError) as exc:
        outcome.record("private", False, f"HeadObject failed after upload: {_storage_failure(exc)}")
        return outcome
    if head is None:
        outcome.record("private", False, "HeadObject reports the object is absent after a GET")
        return outcome
    outcome.head_content_length = head.content_length
    outcome.head_content_type = head.content_type
    outcome.head_cache_control = head.cache_control

    if head.content_length != len(source_bytes):
        outcome.record(
            "private",
            False,
            f"HEAD content length {head.content_length} != verified source {len(source_bytes)}",
        )
        return outcome
    if head.content_type != CONTENT_TYPE:
        outcome.record(
            "private",
            False,
            f"HEAD content type {head.content_type!r} != {CONTENT_TYPE!r}",
        )
        return outcome
    # "Where present": an object this run uploaded must carry the immutable
    # policy. One that was already there may predate it, so a missing value is
    # reported, not failed - but a *different* one is a real mismatch.
    if head.cache_control is not None and head.cache_control != CACHE_CONTROL:
        outcome.record(
            "private",
            False,
            f"HEAD cache-control {head.cache_control!r} != {CACHE_CONTROL!r}",
        )
        return outcome
    if head.cache_control is None and outcome.uploaded:
        outcome.record(
            "private",
            False,
            f"HEAD reports no cache-control on an object this run uploaded with "
            f"{CACHE_CONTROL!r}",
        )
        return outcome
    outcome.record(
        "private",
        True,
        f"authenticated GET returned {len(returned)} bytes, sha256 matches stored evidence; "
        f"HEAD content_type={head.content_type!r}, cache_control={head.cache_control!r}",
    )

    # --- public ------------------------------------------------------------
    try:
        fetched = public_fetcher(outcome.public_url)
    except Exception as exc:  # transport-level; reported, never retried
        outcome.record("public", False, f"the unauthenticated GET never completed: {type(exc).__name__}")
        return outcome

    outcome.public_status = fetched.http_status
    outcome.public_byte_length = len(fetched.body)
    outcome.public_sha256 = hashlib.sha256(fetched.body).hexdigest()

    leaked = fetched.credential_headers_sent
    if leaked:
        outcome.record(
            "public",
            False,
            f"the request carried credential header(s) {leaked} and was therefore not a "
            "public read; nothing about public delivery is proven.",
        )
        return outcome
    if fetched.http_status != 200:
        outcome.record("public", False, f"HTTP {fetched.http_status} from the public origin")
        return outcome
    if outcome.public_byte_length != len(source_bytes):
        outcome.record(
            "public",
            False,
            f"byte length {outcome.public_byte_length} != verified source {len(source_bytes)}",
        )
        return outcome
    if outcome.public_sha256 != evidence.existing_sha256:
        outcome.record(
            "public",
            False,
            f"SHA-256 {outcome.public_sha256} != stored fetch.sha256 {evidence.existing_sha256}",
        )
        return outcome
    if fetched.body != source_bytes:
        outcome.record("public", False, "digests agree but the raw bytes differ")
        return outcome

    # Decode what the *public* origin served, not what was uploaded. The
    # frontend's bounded-presentation guard compares the browser's
    # naturalWidth/naturalHeight against the recorded canvas_px and silently
    # falls back to unbounded contain on any mismatch - so this is the check
    # that the guard will still activate for an R2-served asset.
    try:
        inspection = inspect_image(fetched.body)
    except Exception as exc:
        outcome.record("public", False, f"public bytes failed to decode: {type(exc).__name__}")
        return outcome
    outcome.public_dimensions = (inspection.width, inspection.height)
    if outcome.public_dimensions != evidence.canvas_px:
        outcome.record(
            "public",
            False,
            f"public bytes decode to {inspection.width}x{inspection.height} != stored "
            f"geometry.canvas_px {evidence.canvas_px[0]}x{evidence.canvas_px[1]} - the "
            "frontend geometry guard would fall back to unbounded presentation",
        )
        return outcome
    outcome.record(
        "public",
        True,
        f"HTTP 200, {outcome.public_byte_length} bytes, unauthenticated, sha256 matches "
        f"stored evidence, decodes to {inspection.width}x{inspection.height} "
        f"(== stored canvas_px), format {inspection.image_format}",
    )

    # --- db ----------------------------------------------------------------
    # Not decoration: this tranche's central promise is that mirroring is
    # storage-only. Asserted against the session rather than trusted.
    pending = list(db.new) + list(db.dirty) + list(db.deleted)
    if pending:
        outcome.record(
            "db",
            False,
            f"the session holds {len(pending)} pending change(s) - this command must "
            "write nothing to the database",
        )
        return outcome
    outcome.record(
        "db",
        True,
        "session holds no pending insert, update or delete - nothing was written to the "
        "database",
    )
    return outcome
