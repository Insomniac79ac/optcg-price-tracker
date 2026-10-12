"""Self-hosted official card images: mirror, read path and health check.

Pins the properties the owner asked for: original bytes only (digest ==
artwork_key == R2 == public), objects never overwritten, insert-only rows
versioned by source_url, polite pacing with containment on repeated source
failure, and a read path that falls back to the original URL whenever no
verified copy of the *current* image version exists.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

import pytest
from PIL import Image
from sqlalchemy import select

from app.official_images.health import check_health
from app.official_images.mirror import (
    MIN_INTERVAL_FLOOR,
    Pacer,
    PermanentSourceError,
    Target,
    TransientSourceError,
    mirror_one,
    pending_targets,
    run_mirror,
)
from app.official_images.models import CardPrintImageAsset
from app.services.display_image import get_display_images_for_prints
from app.services.display_image_object_key import object_key
from app.settings import settings
from tests.test_prints import make_canonical, make_print  # noqa: F401

PUBLIC_BASE = "https://pub-test.r2.dev"
OFFICIAL = "https://www.onepiece-cardgame.com/images/cardlist/card/{}.png?260821"


def png_bytes(color=(10, 20, 30), size=(60, 84)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


@dataclass
class Head:
    content_length: int
    content_type: str
    cache_control: str | None


class FakeStorage:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, str, str | None]] = {}
        self.puts: list[str] = []
        self.corrupt_private = False

    def head_object(self, key):
        if key not in self.objects:
            return None
        body, ctype, cache = self.objects[key]
        return Head(len(body), ctype, cache)

    def put_object(self, key, body, *, content_type=None, cache_control=None, metadata=None):
        assert key not in self.objects, "never overwrite"
        self.puts.append(key)
        self.objects[key] = (bytes(body), content_type, cache_control)

    def get_object_bytes(self, key):
        body = self.objects[key][0]
        return body + b"x" if self.corrupt_private else body

    def public_url(self, key):
        return f"{PUBLIC_BASE}/{key}"

    def public_fetch(self, url):
        key = url.removeprefix(PUBLIC_BASE + "/")
        return (200, self.objects[key][0]) if key in self.objects else (404, b"")


@pytest.fixture(autouse=True)
def public_base(monkeypatch):
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", PUBLIC_BASE)


def official_print(db_session, code="OP01-013", body=None, **overrides):
    body = body if body is not None else png_bytes()
    canonical = make_canonical(db_session, card_code=code)
    row = make_print(
        db_session, canonical, image_url=OFFICIAL.format(code), artwork_key=sha(body), **overrides
    )
    return row, body


def target(row) -> Target:
    return Target(row.id, row.image_url, row.artwork_key)


def test_mirror_uploads_exact_bytes_and_records_one_row(db_session):
    row, body = official_print(db_session)
    storage = FakeStorage()

    outcome = mirror_one(db_session, target(row), storage, body, public_fetch=storage.public_fetch)

    key = object_key(sha(body), "png")
    assert outcome.status == "mirrored" and outcome.object_key == key
    assert storage.objects[key][0] == body  # original bytes, untouched
    assert storage.objects[key][2] == "public, max-age=31536000, immutable"
    asset = db_session.scalars(select(CardPrintImageAsset)).one()
    assert (asset.card_print_id, asset.source_url, asset.sha256) == (row.id, row.image_url, sha(body))
    assert (asset.byte_size, asset.width, asset.height, asset.content_type) == (len(body), 60, 84, "image/png")


def test_existing_object_is_reused_never_overwritten(db_session):
    row, body = official_print(db_session)
    storage = FakeStorage()
    key = object_key(sha(body), "png")
    storage.objects[key] = (body, "image/png", "public, max-age=31536000, immutable")

    outcome = mirror_one(db_session, target(row), storage, body, public_fetch=storage.public_fetch)

    assert outcome.status == "reused" and storage.puts == []
    assert db_session.scalars(select(CardPrintImageAsset)).one().object_key == key


def test_digest_mismatch_uploads_and_records_nothing(db_session):
    row, _ = official_print(db_session)
    storage = FakeStorage()

    outcome = mirror_one(
        db_session, target(row), storage, png_bytes(color=(1, 2, 3)), public_fetch=storage.public_fetch
    )

    assert outcome.status == "digest_mismatch"
    assert storage.objects == {} and db_session.scalars(select(CardPrintImageAsset)).all() == []


def test_private_readback_mismatch_records_nothing(db_session):
    row, body = official_print(db_session)
    storage = FakeStorage()
    storage.corrupt_private = True

    outcome = mirror_one(db_session, target(row), storage, body, public_fetch=storage.public_fetch)

    assert outcome.status == "failed" and "private" in outcome.reason
    assert db_session.scalars(select(CardPrintImageAsset)).all() == []


def test_public_mismatch_records_nothing(db_session):
    row, body = official_print(db_session)
    storage = FakeStorage()

    outcome = mirror_one(db_session, target(row), storage, body, public_fetch=lambda url: (200, b"other"))

    assert outcome.status == "failed" and "public" in outcome.reason
    assert db_session.scalars(select(CardPrintImageAsset)).all() == []


def test_pending_targets_skip_recorded_versions_and_non_official_urls(db_session):
    first, body = official_print(db_session, "OP01-001")
    official_print(db_session, "OP01-002", body=png_bytes(color=(9, 9, 9)))
    other_canonical = make_canonical(db_session, card_code="OP01-003")
    make_print(db_session, other_canonical, image_url="https://images.example.com/x.png", artwork_key="a" * 64)
    storage = FakeStorage()
    mirror_one(db_session, target(first), storage, body, public_fetch=storage.public_fetch)

    assert [t.card_print_id for t in pending_targets(db_session)] == [first.id + 1]

    # A new Bandai version is a new URL: pending again, old row kept.
    first.image_url = first.image_url.replace("?260821", "?261101")
    db_session.commit()
    assert first.id in [t.card_print_id for t in pending_targets(db_session)]
    assert len(db_session.scalars(select(CardPrintImageAsset)).all()) == 1


def test_pacer_never_allows_more_than_one_request_per_second():
    now = [0.0]
    slept = []
    pacer = Pacer(0.1, clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    assert pacer.interval == MIN_INTERVAL_FLOOR
    pacer.wait()
    pacer.wait()
    assert slept == [pytest.approx(1.0)]


def test_run_retries_transient_then_stops_after_repeated_failures(db_session):
    rows = [official_print(db_session, f"OP02-00{i}", body=png_bytes(color=(i, 0, 0)))[0] for i in range(1, 4)]
    storage = FakeStorage()
    calls = []

    def always_busy(url):
        calls.append(url)
        raise TransientSourceError("http 503")

    report = run_mirror(db_session, storage, [target(r) for r in rows], fetcher=always_busy,
                        public_fetch=storage.public_fetch, sleep=lambda s: None)

    assert report.stopped and "consecutive transient" in report.stopped
    assert len(calls) == 5 and storage.puts == []
    assert not report.ok


def test_run_records_permanent_failures_and_continues(db_session):
    bad, _ = official_print(db_session, "OP03-001", body=png_bytes(color=(5, 5, 5)))
    good, good_body = official_print(db_session, "OP03-002", body=png_bytes(color=(6, 6, 6)))
    storage = FakeStorage()

    def fetch(url):
        if url == bad.image_url:
            raise PermanentSourceError("http 404")
        return good_body

    report = run_mirror(db_session, storage, [target(bad), target(good)], fetcher=fetch,
                        public_fetch=storage.public_fetch, sleep=lambda s: None)

    assert (report.failed, report.mirrored, report.source_requests) == (1, 1, 2)
    assert report.summary()["problems"] == [{"card_print_id": bad.id, "status": "failed", "reason": "source: http 404"}]


def test_read_path_serves_verified_copy_of_the_current_version_only(db_session):
    row, body = official_print(db_session)
    storage = FakeStorage()
    mirror_one(db_session, target(row), storage, body, public_fetch=storage.public_fetch)

    image = get_display_images_for_prints(db_session, [row])[row.id]
    assert image.url == f"{PUBLIC_BASE}/{object_key(sha(body), 'png')}"
    assert image.source == "bandai" and image.owned_asset_selected is True

    # Bandai publishes a new version: fall back to the original URL (proxied by
    # the frontend) until the new version is mirrored and verified.
    row.image_url = row.image_url.replace("?260821", "?261101")
    db_session.commit()
    image = get_display_images_for_prints(db_session, [row])[row.id]
    assert image.url == row.image_url and image.owned_asset_selected is False


def test_read_path_ignores_a_row_whose_digest_is_not_the_artwork_key(db_session, monkeypatch):
    row, body = official_print(db_session)
    other = png_bytes(color=(200, 0, 0))
    db_session.add(CardPrintImageAsset(
        card_print_id=row.id, source_url=row.image_url, sha256=sha(other),
        object_key=object_key(sha(other), "png"), byte_size=len(other), width=60, height=84,
        content_type="image/png", cache_control=None, verification_method="source_private_public_sha256",
        mirrored_at=row.created_at,
    ))
    db_session.commit()

    image = get_display_images_for_prints(db_session, [row])[row.id]
    assert image.url == row.image_url and image.owned_asset_selected is False


def test_read_path_falls_back_when_public_base_is_unset(db_session, monkeypatch):
    row, body = official_print(db_session)
    storage = FakeStorage()
    mirror_one(db_session, target(row), storage, body, public_fetch=storage.public_fetch)
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", None)

    image = get_display_images_for_prints(db_session, [row])[row.id]
    assert image.url == row.image_url and image.owned_asset_selected is False


def test_health_is_silent_when_every_print_has_a_verified_copy(db_session):
    row, body = official_print(db_session)
    storage = FakeStorage()
    mirror_one(db_session, target(row), storage, body, public_fetch=storage.public_fetch)

    report = check_health(db_session, storage)
    assert report.healthy and report.objects_checked == 1


def test_health_reports_missing_copies_and_missing_objects(db_session):
    mirrored, body = official_print(db_session, "OP04-001")
    missing, _ = official_print(db_session, "OP04-002", body=png_bytes(color=(7, 7, 7)))
    storage = FakeStorage()
    mirror_one(db_session, target(mirrored), storage, body, public_fetch=storage.public_fetch)
    storage.objects.clear()

    report = check_health(db_session, storage)
    assert report.missing_copy == [missing.id]
    assert report.missing_object == [mirrored.id]
    assert not report.healthy
