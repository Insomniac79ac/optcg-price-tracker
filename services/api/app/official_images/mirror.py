"""Mirror official Bandai card images to R2, verified end to end.

One print at a time, in card_print_id order:

    fetch    GET the print's exact ``image_url`` from www.onepiece-cardgame.com
             (https only, no redirects, image/* only, size-capped)
    digest   SHA-256 of those bytes must equal ``card_prints.artwork_key`` -
             the first-party digest recorded when the print was imported. A
             mismatch is reported and nothing is uploaded or recorded.
    decode   decoded for inspection only (format, width, height); the bytes
             are never re-encoded, resized, cropped or watermarked
    key      display-images/sha256/<ab>/<digest>.<ext>, the shared rule
    head     an object already at the key is reused, never overwritten
    upload   PUT the exact fetched bytes, only when the key is empty
    private  authenticated GET: digest must match
    public   unauthenticated GET over R2_PUBLIC_BASE_URL: digest and decoded
             size must match
    record   one insert-only card_print_image_assets row

Requests to Bandai are paced (one at a time, at least ``min_interval``
seconds apart) and transient failures back off exponentially, honouring
Retry-After. Repeated transient failures stop the run: a struggling source is
contained, not retried harder. Reruns skip prints that already have a row for
their current image_url, so the backfill is resume-safe and idempotent.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CardPrint
from app.official_images.models import CardPrintImageAsset
from app.services.display_image_mirror import inspect_image
from app.services.display_image_object_key import OBJECT_KEY_MEDIA_TYPES, object_key
from app.services.object_storage import R2ObjectStorage

SOURCE_HOST = "www.onepiece-cardgame.com"
USER_AGENT = "CardPirateAtlas-official-image-mirror/1.0"
CACHE_CONTROL = "public, max-age=31536000, immutable"
VERIFICATION_METHOD = "source_private_public_sha256"
FETCH_TIMEOUT_SECONDS = 20.0
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # same cap as the frontend image proxy
MIN_INTERVAL_FLOOR = 1.0  # never more than one Bandai request per second
MAX_ATTEMPTS = 3
MAX_CONSECUTIVE_TRANSIENT = 5
BACKOFF_BASE_SECONDS = 5.0
BACKOFF_CAP_SECONDS = 300.0

# Decoded Pillow format -> object-key extension (whose media type is fixed by
# OBJECT_KEY_MEDIA_TYPES, the single source of that pairing).
FORMAT_EXTENSIONS = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}


class TransientSourceError(Exception):
    """Worth retrying later: timeouts, connection errors, 429, 5xx."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class PermanentSourceError(Exception):
    """Not worth retrying: 4xx, redirects, non-images, oversize bodies."""


@dataclass(frozen=True)
class Target:
    card_print_id: int
    source_url: str
    artwork_key: str


@dataclass
class Outcome:
    card_print_id: int
    status: str  # mirrored | reused | digest_mismatch | failed
    reason: str | None = None
    object_key: str | None = None
    byte_size: int | None = None


@dataclass
class RunReport:
    selected: int = 0
    mirrored: int = 0
    reused: int = 0
    digest_mismatch: int = 0
    failed: int = 0
    uploaded_bytes: int = 0
    source_requests: int = 0
    stopped: str | None = None
    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.stopped is None and self.failed == 0 and self.digest_mismatch == 0

    def summary(self) -> dict:
        return {
            "selected": self.selected,
            "mirrored": self.mirrored,
            "reused_existing_object": self.reused,
            "digest_mismatch": self.digest_mismatch,
            "failed": self.failed,
            "uploaded_bytes": self.uploaded_bytes,
            "source_requests": self.source_requests,
            "stopped": self.stopped,
            "problems": [
                {"card_print_id": o.card_print_id, "status": o.status, "reason": o.reason}
                for o in self.outcomes
                if o.status in ("digest_mismatch", "failed")
            ],
        }


def is_official_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == SOURCE_HOST


def pending_targets(
    db: Session, *, print_ids: list[int] | None = None, limit: int | None = None
) -> list[Target]:
    """Active prints whose current official image_url has no recorded copy."""
    recorded = select(CardPrintImageAsset.id).where(
        CardPrintImageAsset.card_print_id == CardPrint.id,
        CardPrintImageAsset.source_url == CardPrint.image_url,
    )
    query = (
        select(CardPrint.id, CardPrint.image_url, CardPrint.artwork_key)
        .where(
            CardPrint.is_active.is_(True),
            CardPrint.image_url.is_not(None),
            CardPrint.artwork_key.is_not(None),
            ~recorded.exists(),
        )
        .order_by(CardPrint.id.asc())
    )
    if print_ids:
        query = query.where(CardPrint.id.in_(print_ids))
    targets = [
        Target(row.id, row.image_url, row.artwork_key)
        for row in db.execute(query)
        if is_official_url(row.image_url)
    ]
    return targets[:limit] if limit is not None else targets


class Pacer:
    """At most one call per `interval` seconds, measured start to start."""

    def __init__(self, interval: float, clock=time.monotonic, sleep=time.sleep):
        self.interval = max(interval, MIN_INTERVAL_FLOOR)
        self._clock, self._sleep = clock, sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            remaining = self.interval - (self._clock() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def fetch_official(url: str, client: httpx.Client) -> bytes:
    if not is_official_url(url):
        raise PermanentSourceError("not an official https card list url")
    try:
        response = client.get(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
    except httpx.TimeoutException as exc:
        raise TransientSourceError(f"timeout: {type(exc).__name__}") from exc
    except httpx.TransportError as exc:
        raise TransientSourceError(f"transport: {type(exc).__name__}") from exc
    if response.status_code == 429 or response.status_code >= 500:
        raise TransientSourceError(f"http {response.status_code}", _retry_after(response))
    if 300 <= response.status_code < 400:
        raise PermanentSourceError(f"redirect {response.status_code}")
    if response.status_code != 200:
        raise PermanentSourceError(f"http {response.status_code}")
    if not (response.headers.get("content-type") or "").startswith("image/"):
        raise PermanentSourceError("response is not an image")
    if len(response.content) > MAX_IMAGE_BYTES:
        raise PermanentSourceError("image too large")
    return response.content


def public_get(url: str, client: httpx.Client) -> tuple[int, bytes]:
    response = client.get(url, headers={"Cache-Control": "no-cache"})
    return response.status_code, response.content


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def mirror_one(
    db: Session,
    target: Target,
    storage: R2ObjectStorage,
    body: bytes,
    *,
    public_fetch: Callable[[str], tuple[int, bytes]],
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> Outcome:
    """Verify, upload if absent, verify again and record. `body` is the
    already-fetched source response for target.source_url."""
    digest = _sha256(body)
    if digest != target.artwork_key:
        return Outcome(target.card_print_id, "digest_mismatch",
                       f"source sha256 {digest[:12]}... != artwork_key {target.artwork_key[:12]}...")
    try:
        inspection = inspect_image(body)
    except Exception as exc:  # undecodable bytes are never uploaded
        return Outcome(target.card_print_id, "failed", f"decode: {type(exc).__name__}")
    extension = FORMAT_EXTENSIONS.get(inspection.image_format or "")
    if extension is None:
        return Outcome(target.card_print_id, "failed", f"unsupported format {inspection.image_format}")
    content_type = OBJECT_KEY_MEDIA_TYPES[extension]
    key = object_key(digest, extension)

    head = storage.head_object(key)
    uploaded = head is None
    if uploaded:
        storage.put_object(key, body, content_type=content_type, cache_control=CACHE_CONTROL)
        head = storage.head_object(key)
        if head is None:
            return Outcome(target.card_print_id, "failed", "object absent after upload", key)
    if head.content_length is not None and head.content_length != len(body):
        return Outcome(target.card_print_id, "failed", "existing object length differs", key)
    if head.content_type and head.content_type.split(";")[0].strip().lower() != content_type:
        return Outcome(target.card_print_id, "failed", "existing object content type differs", key)

    if _sha256(storage.get_object_bytes(key)) != digest:
        return Outcome(target.card_print_id, "failed", "private GET digest mismatch", key)
    status, public_body = public_fetch(storage.public_url(key))
    if status != 200 or _sha256(public_body) != digest:
        return Outcome(target.card_print_id, "failed", f"public GET mismatch (http {status})", key)
    public_inspection = inspect_image(public_body)
    if (public_inspection.width, public_inspection.height) != (inspection.width, inspection.height):
        return Outcome(target.card_print_id, "failed", "public decoded size differs", key)

    db.add(
        CardPrintImageAsset(
            card_print_id=target.card_print_id,
            source_url=target.source_url,
            sha256=digest,
            object_key=key,
            byte_size=len(body),
            width=inspection.width,
            height=inspection.height,
            content_type=content_type,
            cache_control=head.cache_control or (CACHE_CONTROL if uploaded else None),
            verification_method=VERIFICATION_METHOD,
            mirrored_at=now(),
        )
    )
    db.commit()
    return Outcome(target.card_print_id, "mirrored" if uploaded else "reused", None, key, len(body))


def run_mirror(
    db: Session,
    storage: R2ObjectStorage,
    targets: list[Target],
    *,
    min_interval: float = MIN_INTERVAL_FLOOR,
    fetcher: Callable[[str], bytes] | None = None,
    public_fetch: Callable[[str], tuple[int, bytes]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[Outcome], None] | None = None,
) -> RunReport:
    report = RunReport(selected=len(targets))
    pacer = Pacer(min_interval, sleep=sleep)
    with httpx.Client(follow_redirects=False, timeout=FETCH_TIMEOUT_SECONDS) as client:
        fetch = fetcher or (lambda url: fetch_official(url, client))
        pub = public_fetch or (lambda url: public_get(url, client))
        consecutive_transient = 0
        for target in targets:
            body, last = None, None
            for attempt in range(1, MAX_ATTEMPTS + 1):
                pacer.wait()
                report.source_requests += 1
                try:
                    body = fetch(target.source_url)
                    consecutive_transient = 0
                    break
                except TransientSourceError as exc:
                    consecutive_transient += 1
                    if consecutive_transient >= MAX_CONSECUTIVE_TRANSIENT:
                        report.stopped = f"{consecutive_transient} consecutive transient source failures (last: {exc})"
                        break
                    delay = exc.retry_after or min(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1), BACKOFF_CAP_SECONDS)
                    sleep(min(delay, BACKOFF_CAP_SECONDS))
                    last = f"transient: {exc}"
                except PermanentSourceError as exc:
                    last = f"source: {exc}"
                    break
            if report.stopped:
                break
            if body is None:
                outcome = Outcome(target.card_print_id, "failed", last)
            else:
                try:
                    outcome = mirror_one(db, target, storage, body, public_fetch=pub)
                except Exception as exc:  # storage/database failure: record and continue
                    db.rollback()
                    outcome = Outcome(target.card_print_id, "failed", f"{type(exc).__name__}")
            report.outcomes.append(outcome)
            if outcome.status == "mirrored":
                report.mirrored += 1
                report.uploaded_bytes += outcome.byte_size or 0
            elif outcome.status == "reused":
                report.reused += 1
            elif outcome.status == "digest_mismatch":
                report.digest_mismatch += 1
            else:
                report.failed += 1
            if progress:
                progress(outcome)
    return report
