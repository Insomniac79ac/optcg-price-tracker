"""Verification half of the display-image mirroring pipeline, plus the
bootstrap-digest persistence that follows from it.

This module answers one question, for the approved SNKRDUNK display images
only: *does the asset we would mirror today still match the evidence that was
retained when it was verified on 2026-08-13?* It fetches, hashes, decodes and
compares. It contacts no object storage (none exists yet: see
docs/r2_image_mirroring_audit_2026-08-13.pdf section O, and
docs/display_image_mirror_dry_run_2026-08-14.pdf for the 16/16 dry-run result
that this persistence step is built on).

The only write it can perform is additive and explicit: three new keys inside
each verified asset's existing ``display_image.fetch`` block, recording the
full SHA-256 computed during that same run. See persist_bootstrap_digests -
it is never reached unless the caller asks for it, and never unless every
selected asset verified first.

What a PASS means, stated precisely, because it is easy to overclaim: the
retained evidence holds ``fetch.sha256_prefix``, the first 16 hex characters
(64 bits) of a SHA-256 - **no full historical digest of any image exists
anywhere**. So a PASS says the current fetch matches the retained truncated
byte-hash prefix, the exact byte length, the recorded canvas dimensions and
the recorded alpha geometry. It does *not* prove historical full-byte
equality, and must never be described that way. The full SHA-256 computed here
is the *bootstrap* digest a later mirroring tranche would persist and use as
the content-addressed object key.

Byte discipline: exactly one authoritative buffer per asset - the HTTP
response body. It is hashed as-is and handed to Pillow through a BytesIO for
*inspection only*. Pillow is never asked to produce bytes: no ``Image.save``,
no re-encode, resize, crop or format conversion appears in this module or may
ever be added to it, because the mirroring tranche that follows will upload
this same buffer verbatim. The image bytes themselves are never persisted.

Fail-closed throughout. Eligibility reuses the live selection predicate rather
than re-implementing it, so an asset can only be verified here if the public
API would actually serve it.
"""

from __future__ import annotations

import copy
import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlparse

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Source, SourceCardMapping

# Deliberately the *same* predicate GET /prints selects with, imported rather
# than copied: a second implementation could drift and let this dry-run bless
# an asset the public API would refuse (or vice versa). display_image.py is
# not modified by this tranche.
from app.services.display_image import DISPLAY_SOURCE_PRIORITY
from app.services.display_image import _qualifies as display_image_qualifies

# The 16 approved SNKRDUNK display assets as of 2026-08-13. Used only to
# report drift in the selected population - never to drive selection, which
# stays fully evidence-driven.
EXPECTED_APPROVED_ASSET_COUNT = 16

# Mappings 42/43/49/52 are quarantined pending human artwork review and carry
# no display_image evidence. Named explicitly as a second, independent guard:
# selection would already reject them (review_status != 'approved'), and this
# ensures they can never be mirrored even if evidence were attached later.
QUARANTINED_MAPPING_IDS = frozenset({42, 43, 49, 52})

# Where a display image is allowed to come from, per source. URLs are used
# verbatim from evidence and never reconstructed; this only bounds the host.
EXPECTED_IMAGE_HOSTS: dict[str, str] = {"snkrdunk": "cdn.snkrdunk.com"}

# Decoded-format allowlist -> (object-key extension, canonical media type).
# The extension comes from the *decoded* format, never from the URL, because
# SNKRDUNK URLs carry query parameters (".webp?size=l").
SUPPORTED_FORMATS: dict[str, tuple[str, str]] = {
    "WEBP": ("webp", "image/webp"),
    "PNG": ("png", "image/png"),
    "JPEG": ("jpg", "image/jpeg"),
}

# Fixed and explicit so a future run cannot drift with httpx's defaults, and
# so a content-negotiating CDN is asked for the same variant every time.
ACCEPT_HEADER = "image/webp,image/png,image/*;q=0.8"
USER_AGENT = "CardPirateAtlas-display-image-mirror/1.0 (+verification-dry-run)"
FETCH_TIMEOUT_SECONDS = 20.0
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # same cap the frontend image proxy uses

OBJECT_KEY_PREFIX = "display-images/sha256"

# The three additive keys persistence writes into an existing `fetch` block,
# and nothing else. `sha256_prefix`, `bytes` and `fetched_at` all stay exactly
# as the 2026-08-13 verification wrote them.
SHA256_KEY = "sha256"
SHA256_RECORDED_AT_KEY = "sha256_recorded_at"
SHA256_ORIGIN_KEY = "sha256_origin"

# Provenance, stated so the record cannot later be misread as historical: the
# full digest was NOT retained from the original fetch. It was established by
# a later re-fetch that matched the retained 64-bit prefix, byte length,
# dimensions, alpha geometry and format. Hence a separate recorded-at
# timestamp - `fetch.fetched_at` keeps pointing at the historical fetch.
BOOTSTRAP_SHA256_ORIGIN = "bootstrap_refetch"

# Accurate one-line statement of what a full PASS establishes. Reused by the
# CLI and pinned by a test so the weaker claim cannot quietly become a
# stronger one.
PASS_SEMANTICS = (
    "Current fetch matches retained truncated byte-hash prefix, exact byte length, "
    "recorded dimensions and recorded alpha geometry. Full SHA-256 computed now for "
    "future content-addressed mirroring. This is NOT proof of historical full-byte "
    "equality - no historical full digest exists."
)


# --- retained evidence ------------------------------------------------------


@dataclass(frozen=True)
class RetainedEvidence:
    """The subset of a mapping's retained display_image block this dry-run
    checks against. Built only for mappings that already passed eligibility."""

    mapping_id: int
    card_print_id: int
    source: str
    url: str
    sha256_prefix: str
    byte_length: int
    content_type: str
    http_status: int
    final_host: str
    redirected: bool
    canvas_px: tuple[int, int]
    card_bbox_px: tuple[int, int, int, int]  # INCLUSIVE corners, as stored
    card_px: tuple[int, int] | None
    # Row state and payload identity, carried so the write phase can prove
    # nothing moved underneath it between verification and persistence.
    is_active: bool
    review_status: str
    manual_verified: bool
    classification: str
    payload_card_print_id: int
    # A full digest persisted by an earlier bootstrap run, if any. None means
    # this asset has not been bootstrapped yet.
    existing_sha256: str | None

    @property
    def write_fingerprint(self) -> tuple:
        """Everything that must still hold at write time for the verification
        result to apply to this row. Compared whole: if any element differs
        from what was verified, the entire batch is rolled back rather than
        written against evidence nobody checked."""
        return (
            self.mapping_id,
            self.card_print_id,
            self.is_active,
            self.review_status,
            self.manual_verified,
            self.classification,
            self.source,
            self.payload_card_print_id,
            self.url,
            self.sha256_prefix,
            self.byte_length,
            self.canvas_px,
            self.card_bbox_px,
            self.card_px,
        )


@dataclass(frozen=True)
class SkippedMapping:
    mapping_id: int
    card_print_id: int | None
    reason: str
    quarantined: bool = False


def _ints(value: object, count: int) -> tuple[int, ...] | None:
    """Exactly `count` real integers, or None. Bools are rejected - they are
    ints in Python, and one here means malformed evidence (same rule as
    app.services.display_image._ints)."""
    if not isinstance(value, (list, tuple)) or len(value) != count:
        return None
    out: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            return None
        out.append(item)
    return tuple(out)


def _is_hex(value: str) -> bool:
    return all(c in "0123456789abcdef" for c in value)


def _evidence_from_payload(
    mapping: SourceCardMapping, source_name: str, payload: dict
) -> RetainedEvidence | str:
    """Build RetainedEvidence, or return a string reason why the payload is
    unusable. Everything needed for a check must be present and well-formed;
    there are no defaults, because a defaulted value would silently weaken a
    comparison."""
    if payload.get("source") != source_name:
        return f"evidence source {payload.get('source')!r} != mapping source {source_name!r}"
    if payload.get("source_card_mapping_id") != mapping.id:
        return (
            f"evidence source_card_mapping_id {payload.get('source_card_mapping_id')!r} "
            f"!= mapping id {mapping.id}"
        )

    url = payload.get("url")
    parsed = urlparse(url or "")
    expected_host = EXPECTED_IMAGE_HOSTS.get(source_name)
    if parsed.scheme != "https":
        return "evidence url is not https"
    if expected_host is None or parsed.hostname != expected_host:
        return f"evidence url host {parsed.hostname!r} != expected {expected_host!r}"

    fetch = payload.get("fetch")
    if not isinstance(fetch, dict):
        return "evidence has no fetch block"

    prefix = fetch.get("sha256_prefix")
    if not isinstance(prefix, str) or len(prefix) != 16 or not _is_hex(prefix.lower()):
        return f"evidence sha256_prefix {prefix!r} is not 16 hex characters"

    byte_length = fetch.get("bytes")
    if isinstance(byte_length, bool) or not isinstance(byte_length, int) or byte_length <= 0:
        return f"evidence fetch.bytes {byte_length!r} is not a positive integer"

    content_type = fetch.get("content_type")
    if not isinstance(content_type, str) or not content_type:
        return "evidence fetch.content_type is missing"

    final_host = fetch.get("final_host")
    if not isinstance(final_host, str) or final_host != parsed.hostname:
        return f"evidence fetch.final_host {final_host!r} != url host {parsed.hostname!r}"

    http_status = fetch.get("http_status")
    if isinstance(http_status, bool) or not isinstance(http_status, int):
        return f"evidence fetch.http_status {http_status!r} is not an integer"

    # An already-bootstrapped asset carries a full digest. It is never
    # overwritten - it is either confirmed by this run or the batch fails - so
    # a malformed one is rejected here rather than compared loosely later.
    existing_sha256 = fetch.get(SHA256_KEY)
    if existing_sha256 is not None:
        if (
            not isinstance(existing_sha256, str)
            or len(existing_sha256) != 64
            or not _is_hex(existing_sha256)
        ):
            return f"evidence fetch.sha256 {existing_sha256!r} is not 64 lowercase hex characters"
        if not existing_sha256.startswith(prefix.lower()):
            return (
                f"evidence fetch.sha256 does not start with fetch.sha256_prefix "
                f"{prefix.lower()!r} - the record is internally inconsistent"
            )

    geometry = payload.get("geometry")
    if not isinstance(geometry, dict):
        return "evidence has no geometry block"
    canvas = _ints(geometry.get("canvas_px"), 2)
    bbox = _ints(geometry.get("card_bbox_px"), 4)
    if canvas is None:
        return "evidence geometry.canvas_px is malformed"
    if bbox is None:
        return "evidence geometry.card_bbox_px is malformed"
    card_px = _ints(geometry.get("card_px"), 2)

    return RetainedEvidence(
        mapping_id=mapping.id,
        card_print_id=mapping.card_print_id,
        source=source_name,
        url=url,
        sha256_prefix=prefix.lower(),
        byte_length=byte_length,
        content_type=content_type,
        http_status=http_status,
        final_host=final_host,
        redirected=bool(fetch.get("redirected")),
        canvas_px=(canvas[0], canvas[1]),
        card_bbox_px=(bbox[0], bbox[1], bbox[2], bbox[3]),
        card_px=(card_px[0], card_px[1]) if card_px is not None else None,
        is_active=bool(mapping.is_active),
        review_status=mapping.review_status,
        manual_verified=bool(mapping.manual_verified),
        classification=payload.get("classification"),
        payload_card_print_id=payload.get("card_print_id"),
        existing_sha256=existing_sha256,
    )


def collect_candidates(
    db: Session, card_print_ids: list[int] | None = None
) -> tuple[list[RetainedEvidence], list[SkippedMapping]]:
    """Select the mappings whose display image is eligible for mirroring.

    Read-only: one SELECT, no flush, no write. Every mapping on a
    display-eligible source is examined so the run can *report* why the
    ineligible ones were skipped, but eligibility itself fails closed - a
    mapping is only a candidate when it is active, approved, manually
    verified, not quarantined, and its retained evidence still satisfies the
    live selection predicate for its own card_print_id.
    """
    stmt = (
        select(SourceCardMapping, Source.name)
        .join(Source, Source.id == SourceCardMapping.source_id)
        .where(Source.name.in_(DISPLAY_SOURCE_PRIORITY))
        .order_by(SourceCardMapping.id.asc())
    )
    if card_print_ids is not None:
        stmt = stmt.where(SourceCardMapping.card_print_id.in_(card_print_ids))

    candidates: list[RetainedEvidence] = []
    skipped: list[SkippedMapping] = []

    for mapping, source_name in db.execute(stmt).all():
        if mapping.id in QUARANTINED_MAPPING_IDS:
            skipped.append(
                SkippedMapping(mapping.id, mapping.card_print_id, "quarantined", quarantined=True)
            )
            continue
        if not mapping.is_active:
            skipped.append(SkippedMapping(mapping.id, mapping.card_print_id, "mapping is inactive"))
            continue
        if mapping.review_status != "approved":
            skipped.append(
                SkippedMapping(
                    mapping.id, mapping.card_print_id, f"review_status={mapping.review_status!r}"
                )
            )
            continue
        if not mapping.manual_verified:
            skipped.append(
                SkippedMapping(mapping.id, mapping.card_print_id, "mapping is not manual_verified")
            )
            continue
        if mapping.card_print_id is None:
            skipped.append(SkippedMapping(mapping.id, None, "mapping has no card_print_id"))
            continue

        payload = (mapping.match_explanation_json or {}).get("display_image")
        if not isinstance(payload, dict):
            skipped.append(
                SkippedMapping(mapping.id, mapping.card_print_id, "no display_image evidence")
            )
            continue
        # The public selection contract: VERIFIED_DISPLAY, all four display
        # assertions, https url, and the payload's own card_print_id equal to
        # the mapping's - the check that stops sibling artwork crossing over.
        if not display_image_qualifies(payload, mapping.card_print_id):
            skipped.append(
                SkippedMapping(
                    mapping.id, mapping.card_print_id, "display-image qualification failed"
                )
            )
            continue

        evidence = _evidence_from_payload(mapping, source_name, payload)
        if isinstance(evidence, str):
            skipped.append(SkippedMapping(mapping.id, mapping.card_print_id, evidence))
            continue
        candidates.append(evidence)

    return candidates, skipped


# --- fetch ------------------------------------------------------------------


@dataclass(frozen=True)
class FetchResult:
    http_status: int
    final_url: str
    final_host: str | None
    redirected: bool
    raw_content_type: str | None
    media_type: str | None
    body: bytes


def normalize_media_type(raw: str | None) -> str | None:
    """"image/webp; charset=binary" -> "image/webp"."""
    if raw is None:
        return None
    return raw.split(";")[0].strip().lower() or None


def fetch_image(url: str) -> FetchResult:
    """Fetch the retained URL verbatim, exactly once, with fixed headers.

    Redirects are followed but recorded; the caller rejects a redirect that
    lands on a different host than the evidence recorded. No credentials, no
    cookies, no retry with different headers - a failure here is reported, not
    worked around, because "which headers made it pass" is itself evidence.
    """
    headers = {"Accept": ACCEPT_HEADER, "User-Agent": USER_AGENT}
    with httpx.Client(follow_redirects=True, timeout=FETCH_TIMEOUT_SECONDS) as client:
        response = client.get(url, headers=headers)
    return FetchResult(
        http_status=response.status_code,
        final_url=str(response.url),
        final_host=urlparse(str(response.url)).hostname,
        redirected=bool(response.history),
        raw_content_type=response.headers.get("content-type"),
        media_type=normalize_media_type(response.headers.get("content-type")),
        body=response.content,
    )


Fetcher = Callable[[str], FetchResult]


# --- image inspection -------------------------------------------------------


@dataclass(frozen=True)
class ImageInspection:
    """Everything read out of the decoded image. Decoding produces no bytes:
    the source buffer is untouched and nothing is ever saved."""

    image_format: str | None
    width: int
    height: int
    has_alpha: bool
    alpha_bbox: tuple[int, int, int, int] | None  # Pillow convention: right/bottom EXCLUSIVE


def inspect_image(body: bytes) -> ImageInspection:
    """Decode `body` for inspection only - size, format, alpha presence and
    the non-zero-alpha bounding box."""
    with Image.open(io.BytesIO(body)) as image:
        image_format = image.format
        width, height = image.size

        if "A" in image.getbands():
            alpha = image.getchannel("A")
        elif "transparency" in image.info:
            # Palette transparency: materialise alpha on an inspection copy.
            # This copy is never hashed, uploaded or otherwise returned.
            alpha = image.convert("RGBA").getchannel("A")
        else:
            return ImageInspection(image_format, width, height, has_alpha=False, alpha_bbox=None)

        bbox = alpha.getbbox()

    return ImageInspection(
        image_format=image_format,
        width=width,
        height=height,
        has_alpha=True,
        alpha_bbox=tuple(bbox) if bbox is not None else None,
    )


def inclusive_bbox_to_pillow(bbox: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Retained geometry stores ``[left, top, right, bottom]`` with *inclusive*
    corners (the same convention app.services.display_image._geometry converts
    to width/height by adding 1 per span). Pillow's ``getbbox()`` returns
    right/bottom *exclusive*. Comparing the two directly is off by one pixel on
    each of two sides, so stored bboxes are normalised here and nowhere else.

    Real evidence: stored [241, 51, 614, 573] -> (241, 51, 615, 574), giving
    615-241 = 374 by 574-51 = 523, which is exactly the stored card_px.
    """
    left, top, right_inclusive, bottom_inclusive = bbox
    return (left, top, right_inclusive + 1, bottom_inclusive + 1)


def object_key(sha256_hex: str, extension: str) -> str:
    """The content-addressed key a later tranche would write to. Computed for
    reporting only - this tranche creates no objects and contacts no storage."""
    return f"{OBJECT_KEY_PREFIX}/{sha256_hex[:2]}/{sha256_hex}.{extension}"


# --- verification -----------------------------------------------------------


@dataclass
class AssetVerification:
    """Per-asset dry-run outcome. `passed` is true only when `failures` is
    empty; every field is reported either way so drift can be diagnosed."""

    evidence: RetainedEvidence
    failures: list[str] = field(default_factory=list)
    fetch: FetchResult | None = None
    sha256: str | None = None
    actual_bytes: int | None = None
    inspection: ImageInspection | None = None
    expected_alpha_bbox: tuple[int, int, int, int] | None = None
    image_format: str | None = None
    extension: str | None = None
    proposed_object_key: str | None = None

    @property
    def passed(self) -> bool:
        return not self.failures

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"

    @property
    def sha256_prefix(self) -> str | None:
        return self.sha256[:16] if self.sha256 else None


def verify_asset(evidence: RetainedEvidence, fetcher: Fetcher = fetch_image) -> AssetVerification:
    """Fetch one asset once and check it against its retained evidence.

    A transport- or response-level mismatch (non-200, wrong host, empty body)
    stops that asset immediately - there is nothing meaningful to compare. Past
    that point every remaining check runs and all mismatches are collected,
    because when an asset *has* drifted, "which of hash / length / dimensions /
    alpha changed" is exactly what the next tranche needs to know.
    """
    result = AssetVerification(evidence=evidence)

    try:
        fetched = fetcher(evidence.url)
    except Exception as exc:  # network/DNS/timeout - report, never retry
        result.failures.append(f"fetch failed: {type(exc).__name__}: {exc}")
        return result

    result.fetch = fetched
    result.actual_bytes = len(fetched.body)

    if fetched.http_status != 200:
        result.failures.append(f"http status {fetched.http_status} (expected 200)")
        return result
    if fetched.http_status != evidence.http_status:
        result.failures.append(
            f"http status {fetched.http_status} != retained {evidence.http_status}"
        )
        return result
    if fetched.final_host != evidence.final_host:
        result.failures.append(
            f"final host {fetched.final_host!r} != retained {evidence.final_host!r}"
        )
        return result
    if fetched.redirected != evidence.redirected:
        result.failures.append(
            f"redirected={fetched.redirected} != retained redirected={evidence.redirected}"
        )
        return result
    if not fetched.body:
        result.failures.append("empty response body")
        return result
    if len(fetched.body) > MAX_IMAGE_BYTES:
        result.failures.append(f"body {len(fetched.body)} bytes exceeds cap {MAX_IMAGE_BYTES}")
        return result

    # One authoritative buffer from here on: hashed as-is, inspected via a
    # BytesIO view, never transformed.
    body = fetched.body
    result.sha256 = hashlib.sha256(body).hexdigest()

    if len(body) != evidence.byte_length:
        result.failures.append(f"byte length {len(body)} != retained {evidence.byte_length}")
    if result.sha256[:16] != evidence.sha256_prefix:
        result.failures.append(
            f"sha256 prefix {result.sha256[:16]} != retained {evidence.sha256_prefix}"
        )

    try:
        inspection = inspect_image(body)
    except Exception as exc:
        result.failures.append(f"image decode failed: {type(exc).__name__}: {exc}")
        return result

    result.inspection = inspection
    result.image_format = inspection.image_format

    # Dimensions: load-bearing for the frontend's matchesNaturalSize() guard,
    # which silently falls back to unbounded presentation on any change. The
    # asset must match canvas_px; canvas_px is never adjusted to match it.
    if (inspection.width, inspection.height) != evidence.canvas_px:
        result.failures.append(
            f"canvas {inspection.width}x{inspection.height} != retained "
            f"{evidence.canvas_px[0]}x{evidence.canvas_px[1]}"
        )

    expected_bbox = inclusive_bbox_to_pillow(evidence.card_bbox_px)
    result.expected_alpha_bbox = expected_bbox
    if not inspection.has_alpha:
        result.failures.append("image has no alpha channel")
    elif inspection.alpha_bbox is None:
        result.failures.append("alpha channel is fully transparent (no bbox)")
    elif inspection.alpha_bbox != expected_bbox:
        result.failures.append(
            f"alpha bbox {inspection.alpha_bbox} != retained {expected_bbox} "
            f"(stored inclusive {list(evidence.card_bbox_px)})"
        )
    elif evidence.card_px is not None:
        left, top, right, bottom = inspection.alpha_bbox
        derived = (right - left, bottom - top)
        if derived != evidence.card_px:
            result.failures.append(
                f"alpha bbox size {derived[0]}x{derived[1]} != retained card_px "
                f"{evidence.card_px[0]}x{evidence.card_px[1]}"
            )

    # Format: from the decoder, cross-checked against the response's own
    # content-type and the retained one. Never inferred from the URL suffix,
    # which carries query parameters.
    supported = SUPPORTED_FORMATS.get(inspection.image_format or "")
    if supported is None:
        result.failures.append(f"unsupported decoded format {inspection.image_format!r}")
    else:
        extension, canonical_media_type = supported
        result.extension = extension
        if fetched.media_type != canonical_media_type:
            result.failures.append(
                f"content-type {fetched.media_type!r} != decoded format "
                f"{inspection.image_format} ({canonical_media_type})"
            )
        elif normalize_media_type(evidence.content_type) != canonical_media_type:
            result.failures.append(
                f"retained content_type {evidence.content_type!r} != decoded format "
                f"{inspection.image_format} ({canonical_media_type})"
            )
        if result.passed:
            result.proposed_object_key = object_key(result.sha256, extension)

    return result


@dataclass
class VerificationReport:
    """Whole-run outcome. Counts are what the CLI prints and what the exit
    code is derived from. The same report drives both modes: in dry-run it is
    the end of the story, and in persistence mode `ok` is the precondition
    that has to hold before a single row may be written."""

    verifications: list[AssetVerification]
    skipped: list[SkippedMapping]
    expected_asset_count: int | None = None

    @property
    def selected(self) -> int:
        return len(self.verifications)

    @property
    def attempted(self) -> int:
        return sum(1 for v in self.verifications if v.fetch is not None)

    @property
    def passed(self) -> int:
        return sum(1 for v in self.verifications if v.passed)

    @property
    def failed(self) -> int:
        return sum(1 for v in self.verifications if not v.passed)

    @property
    def quarantined_skipped(self) -> int:
        return sum(1 for s in self.skipped if s.quarantined)

    @property
    def other_skipped(self) -> int:
        return sum(1 for s in self.skipped if not s.quarantined)

    @property
    def population_drift(self) -> str | None:
        """Set when the number of eligible assets is not the number this
        tranche expects - itself a finding, even if every asset passes."""
        if self.expected_asset_count is None or self.selected == self.expected_asset_count:
            return None
        return (
            f"selected {self.selected} eligible assets, expected "
            f"{self.expected_asset_count}"
        )

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.attempted == self.selected and not self.population_drift


def run_verification(
    db: Session,
    card_print_ids: list[int] | None = None,
    fetcher: Fetcher = fetch_image,
    expected_asset_count: int | None = None,
) -> VerificationReport:
    """Verify every eligible display image and return the report.

    Writes nothing anywhere: no DB write, no file, no object storage. This is
    the whole of `--dry-run`, and the mandatory first phase of
    `--persist-bootstrap-sha256`; all network work happens here, before any
    transaction is opened.
    """
    candidates, skipped = collect_candidates(db, card_print_ids)
    verifications = [verify_asset(evidence, fetcher) for evidence in candidates]
    return VerificationReport(
        verifications=verifications,
        skipped=skipped,
        expected_asset_count=expected_asset_count,
    )


# --- bootstrap-digest persistence -------------------------------------------


@dataclass
class PersistOutcome:
    """What the write phase did. `updated` and `already_bootstrapped` are
    mapping ids; `abort_reason` being set means nothing at all was written."""

    updated: list[int] = field(default_factory=list)
    already_bootstrapped: list[int] = field(default_factory=list)
    abort_reason: str | None = None
    recorded_at: str | None = None

    @property
    def ok(self) -> bool:
        return self.abort_reason is None


def _with_bootstrap_digest(explanation: dict, sha256: str, recorded_at: str) -> dict:
    """Return a full copy of `explanation` with the three additive keys set
    inside display_image.fetch, and every other key - inside and outside
    display_image - untouched.

    Deep copy then whole-object assignment is deliberate. Mutating the nested
    dict in place is not reliably detected by SQLAlchemy's change tracking
    (the column is a plain JSON type, with no MutableDict wrapper anywhere in
    this repo), so the write could silently no-op. Assigning a new object is
    also the pattern the existing writers use - see
    app.services.source_mapping_confidence and app.api.admin_snkrdunk_matching.
    """
    updated = copy.deepcopy(explanation)
    fetch = updated["display_image"]["fetch"]
    fetch[SHA256_KEY] = sha256
    fetch[SHA256_RECORDED_AT_KEY] = recorded_at
    fetch[SHA256_ORIGIN_KEY] = BOOTSTRAP_SHA256_ORIGIN
    return updated


def persist_bootstrap_digests(
    db: Session, report: VerificationReport, now: datetime | None = None
) -> PersistOutcome:
    """Persist the full SHA-256 computed during `report`'s verification phase.

    Atomic at the batch level, in two phases with no overlap:

    1. `report` must already be fully OK - every selected asset fetched and
       passed. One failure anywhere means nothing is written. All network
       work is finished by the time this function is called; no fetch happens
       while a transaction is open.
    2. A single short transaction re-reads the same mappings and re-checks
       each one's `write_fingerprint` against what was verified. Any drift -
       a mapping unapproved, deactivated, re-pointed at another print, its
       evidence edited - rolls the whole batch back.

    Idempotent: an asset whose stored digest already equals the one computed
    now is left completely alone. An asset whose stored digest *differs* is a
    hard failure that aborts the batch and never overwrites - once persisted,
    the full digest is the strongest identity evidence the record has, and
    this command is not entitled to revise it.
    """
    outcome = PersistOutcome()

    if not report.ok:
        outcome.abort_reason = (
            f"verification did not pass ({report.passed}/{report.selected} passed, "
            f"{report.failed} failed) - nothing persisted"
        )
        return outcome
    if not report.verifications:
        outcome.abort_reason = "no assets selected - nothing to persist"
        return outcome

    verified_by_mapping = {v.evidence.mapping_id: v for v in report.verifications}

    # End the read transaction the verification phase held, so the re-read
    # below sees the latest committed state rather than an old snapshot.
    db.rollback()

    fresh_candidates, _ = collect_candidates(
        db, card_print_ids=[v.evidence.card_print_id for v in report.verifications]
    )
    fresh_by_mapping = {evidence.mapping_id: evidence for evidence in fresh_candidates}

    pending: list[tuple[SourceCardMapping, str]] = []
    for mapping_id, verification in verified_by_mapping.items():
        fresh = fresh_by_mapping.get(mapping_id)
        if fresh is None:
            outcome.abort_reason = (
                f"mapping {mapping_id} is no longer an eligible display-image asset - "
                "it changed between verification and write"
            )
            db.rollback()
            return outcome
        if fresh.write_fingerprint != verification.evidence.write_fingerprint:
            outcome.abort_reason = (
                f"mapping {mapping_id} evidence changed between verification and write - "
                "stale verification, nothing persisted"
            )
            db.rollback()
            return outcome

        # `existing_sha256` is deliberately not part of write_fingerprint: a
        # digest appearing between the two phases is not drift, it is either
        # the same bootstrap answer (idempotent) or a contradiction (abort).
        digest = verification.sha256
        if fresh.existing_sha256 is not None:
            if fresh.existing_sha256 == digest:
                outcome.already_bootstrapped.append(mapping_id)
                continue
            outcome.abort_reason = (
                f"mapping {mapping_id} already carries fetch.sha256 "
                f"{fresh.existing_sha256} but this run computed {digest} - refusing to "
                "overwrite; nothing persisted"
            )
            db.rollback()
            return outcome

        mapping = db.get(SourceCardMapping, mapping_id)
        if mapping is None:  # pragma: no cover - collect_candidates just read it
            outcome.abort_reason = f"mapping {mapping_id} disappeared before write"
            db.rollback()
            return outcome
        pending.append((mapping, digest))

    if not pending:  # every asset was already bootstrapped - nothing to write
        db.rollback()
        return outcome

    # One timestamp for the batch: these rows are written in a single
    # transaction, so they were recorded at a single moment.
    recorded_at = (now or datetime.now(timezone.utc)).isoformat()
    outcome.recorded_at = recorded_at

    for mapping, digest in pending:
        mapping.match_explanation_json = _with_bootstrap_digest(
            mapping.match_explanation_json, digest, recorded_at
        )
        outcome.updated.append(mapping.id)

    db.commit()
    return outcome
