"""The admin artwork preview: advisory, on demand, and inert.

The point of these tests is not that the preview computes a good answer - that
is app.services.artwork_evidence's job and its own suite. It is that the
preview cannot affect anything: not the resolver, not a candidate, not a
mapping, and not the routine admin pages.
"""

import io

import pytest

from app.models import SnkrdunkCandidate, SourceCardMapping
from app.services.artwork_evidence import STATUS_AMBIGUOUS, STATUS_EXACT, STATUS_UNUSABLE
from app.services.display_image_mirror import FetchResult
from tests.test_exact_print_approval import _canonical, _print, _product  # noqa: F401


def _png(seed: int, size=(120, 168)) -> bytes:
    from PIL import Image, ImageDraw

    w, h = size
    img = Image.new("RGB", (w, h), (250, 250, 250))
    d = ImageDraw.Draw(img)
    rng = seed
    for _ in range(14):
        rng = (rng * 1103515245 + 12345) % 2147483648
        x0, y0 = rng % w, (rng // 7) % h
        d.rectangle(
            [x0, y0, min(w, x0 + 40), min(h, y0 + 50)],
            fill=((rng * 37) % 256, (rng * 91) % 256, (rng * 53) % 256),
        )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class _Recorder:
    """A fetcher that records every URL it is asked for, so a test can assert
    that nothing was fetched at all."""

    def __init__(self, bodies=None, status=200, raises=None):
        self.calls: list[str] = []
        self.bodies = bodies or {}
        self.status = status
        self.raises = raises

    def __call__(self, url: str) -> FetchResult:
        self.calls.append(url)
        if self.raises:
            raise self.raises
        return FetchResult(
            http_status=self.status,
            final_url=url,
            final_host="example.test",
            redirected=False,
            raw_content_type="image/png",
            media_type="image/png",
            body=self.bodies.get(url, _png(1)),
        )


@pytest.fixture()
def scene(db_session):
    """One card code, two printings with different artwork, and a candidate
    whose photo is the second printing's artwork."""
    db = db_session
    product = _product(db, "OP-09")
    canonical = _canonical(db, "OP09-001", name_en="Preview Subject")
    base = _print(db, canonical, product, "base", artwork_key="key-base")
    alt = _print(db, canonical, product, "p1", artwork_key="key-alt")
    base.image_url = "https://cards.test/base.png"
    alt.image_url = "https://cards.test/alt.png"
    candidate = SnkrdunkCandidate(
        source_url="https://snkrdunk.com/en/trading-cards/770001",
        title="Preview Subject C [OP09-001] (Booster)",
        detected_card_code="OP09-001",
        detected_set_code="OP-09",
        image_url="https://cdn.snkrdunk.test/listing.png",
        match_status="suggested",
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return {"db": db, "candidate": candidate, "base": base, "alt": alt}


def _bodies(scene, listing_seed):
    return {
        "https://cdn.snkrdunk.test/listing.png": _png(listing_seed),
        "https://cards.test/base.png": _png(11),
        "https://cards.test/alt.png": _png(99),
    }


# --- it uses the shared module, and reports what that module says -----------


def test_preview_uses_the_shared_artwork_module(scene, monkeypatch):
    """No second copy of the algorithm: the preview must delegate."""
    import app.services.artwork_preview as preview_module

    seen = {}
    real = preview_module.evaluate_artwork

    def spy(listing, officials, **kwargs):
        seen["called"] = True
        seen["prints"] = sorted(officials)
        return real(listing, officials, **kwargs)

    monkeypatch.setattr(preview_module, "evaluate_artwork", spy)
    preview_module.preview_candidate_artwork(
        scene["db"], scene["candidate"], fetcher=_Recorder(_bodies(scene, 11))
    )
    assert seen["called"] is True
    assert seen["prints"] == sorted([scene["base"].id, scene["alt"].id])


def test_preview_corroborates_the_matching_printing(scene):
    from app.services.artwork_preview import preview_candidate_artwork, summary_line

    p = preview_candidate_artwork(
        scene["db"], scene["candidate"], fetcher=_Recorder(_bodies(scene, 11))
    )
    assert p.verdict.status == STATUS_EXACT
    assert p.verdict.card_print_id == scene["base"].id
    assert p.winning_class_is_shared is False
    assert summary_line(p) == f"Corroborates print {scene['base'].id}"


def test_shared_artwork_prints_are_reported_as_indistinguishable(scene):
    """A reprint: two printings, one artwork. The copy must say the image
    cannot separate them rather than pick one."""
    from app.services.artwork_preview import preview_candidate_artwork, summary_line

    scene["alt"].artwork_key = "key-base"  # same official artwork as base
    scene["db"].commit()
    bodies = _bodies(scene, 11)
    bodies["https://cards.test/alt.png"] = _png(11)
    p = preview_candidate_artwork(scene["db"], scene["candidate"], fetcher=_Recorder(bodies))
    assert p.verdict.status == STATUS_AMBIGUOUS
    assert p.winning_class_is_shared is True
    assert "share the same official artwork" in summary_line(p)
    assert p.verdict.card_print_id is None


# --- failure is advisory, never an error page -------------------------------


def test_a_candidate_with_no_image_is_unusable_not_an_error(scene):
    from app.services.artwork_preview import preview_candidate_artwork

    scene["candidate"].image_url = None
    scene["db"].commit()
    r = _Recorder()
    p = preview_candidate_artwork(scene["db"], scene["candidate"], fetcher=r)
    assert p.verdict.status == STATUS_UNUSABLE
    assert r.calls == [], "must not fetch anything when there is no listing image"


@pytest.mark.parametrize(
    "recorder",
    [_Recorder(status=404), _Recorder(raises=TimeoutError("upstream timed out"))],
)
def test_network_failure_produces_a_safe_advisory_result(scene, recorder):
    from app.services.artwork_preview import preview_candidate_artwork

    p = preview_candidate_artwork(scene["db"], scene["candidate"], fetcher=recorder)
    assert p.verdict.status == STATUS_UNUSABLE
    assert p.fetch_errors


def test_endpoint_returns_advisory_payload(client, scene, monkeypatch):
    import app.api.admin_snkrdunk_matching as router_module
    import app.services.artwork_preview as preview_module

    monkeypatch.setattr(
        router_module,
        "preview_candidate_artwork",
        lambda db, candidate, **kw: preview_module.preview_candidate_artwork(
            db, candidate, fetcher=_Recorder(_bodies(scene, 11))
        ),
    )
    response = client.post(
        f"/admin/snkrdunk-candidates/{scene['candidate'].id}/artwork-preview"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["advisory_only"] is True
    assert body["status"] == "exact"
    assert body["corroborates_card_print_id"] == scene["base"].id
    assert body["method_version"].startswith("artwork-evidence/")
    assert body["listing_image_url"] == "https://cdn.snkrdunk.test/listing.png"
    # Nothing that reads as authoritative.
    for forbidden in ("confidence", "approved", "safe", "recommendation"):
        assert forbidden not in body


def test_endpoint_404s_for_an_unknown_candidate(client, db_session):
    assert client.post("/admin/snkrdunk-candidates/999999/artwork-preview").status_code == 404


# --- inertness --------------------------------------------------------------


def test_preview_mutates_no_candidate_or_mapping_state(client, scene, monkeypatch):
    import app.api.admin_snkrdunk_matching as router_module
    import app.services.artwork_preview as preview_module

    db = scene["db"]
    before = (
        scene["candidate"].match_status,
        scene["candidate"].matched_card_id,
        db.query(SourceCardMapping).count(),
        db.query(SnkrdunkCandidate).count(),
    )
    monkeypatch.setattr(
        router_module,
        "preview_candidate_artwork",
        lambda d, c, **kw: preview_module.preview_candidate_artwork(
            d, c, fetcher=_Recorder(_bodies(scene, 11))
        ),
    )
    assert client.post(
        f"/admin/snkrdunk-candidates/{scene['candidate'].id}/artwork-preview"
    ).status_code == 200

    db.expire_all()
    candidate = db.get(SnkrdunkCandidate, scene["candidate"].id)
    assert (
        candidate.match_status,
        candidate.matched_card_id,
        db.query(SourceCardMapping).count(),
        db.query(SnkrdunkCandidate).count(),
    ) == before


def test_loading_the_normal_admin_pages_fetches_no_images(client, scene, monkeypatch):
    """The whole reason the preview is its own endpoint: browsing the queue
    must not reach out to a marketplace CDN."""
    import app.services.artwork_preview as preview_module

    recorder = _Recorder(_bodies(scene, 11))
    monkeypatch.setattr(preview_module, "fetch_image", recorder)

    assert client.get("/admin/snkrdunk-candidates/matches".replace("/matches", "")
                      + f"/{scene['candidate'].id}/matches").status_code == 200
    assert client.get(
        f"/admin/snkrdunk-candidates/{scene['candidate'].id}/print-options"
    ).status_code == 200
    assert recorder.calls == [], "no image fetch may happen on a normal admin page load"


def test_resolver_output_is_unchanged_by_the_preview(scene):
    """The resolver must answer identically whether or not a preview ran."""
    from app.services.exact_print_approval import (
        ExactPrintApprovalError,
        SourceEvidence,
        resolve_exact_print,
    )
    from app.services.artwork_preview import preview_candidate_artwork

    evidence = SourceEvidence(source_name="snkrdunk", card_code="OP09-001", set_code="OP-09")

    def resolve():
        try:
            decision = resolve_exact_print(
                scene["db"], card_print_id=scene["base"].id, evidence=evidence
            )
            return ("ok", decision.card_print.id, tuple(decision.evidence_used))
        except ExactPrintApprovalError as exc:
            return ("refused", exc.code, tuple(exc.alternatives))

    before = resolve()
    preview_candidate_artwork(
        scene["db"], scene["candidate"], fetcher=_Recorder(_bodies(scene, 11))
    )
    assert resolve() == before
    # And the refusal is still the ambiguity one - artwork changed nothing.
    assert before[0] == "refused"
    assert before[1] == "evidence_cannot_distinguish_print"
