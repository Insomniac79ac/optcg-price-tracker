"""Artwork as an exact-print evidence channel, and its containment.

Two halves: the pure ranking module, and its (flag-gated) effect on
resolve_exact_print. The second half matters most - artwork is only ever
allowed to REMOVE a printing from a set some other channel already permitted,
and with the flag off it must be as if the channel did not exist.

Images here are generated deterministically in-process, so these tests need no
network and no fixtures on disk.
"""

import hashlib
import io

import pytest

from app.services.artwork_evidence import (
    ARTWORK_METHOD_VERSION,
    STATUS_AMBIGUOUS,
    STATUS_EXACT,
    STATUS_NO_MATCH,
    STATUS_UNUSABLE,
    ArtworkVerdict,
    evaluate_artwork,
    official_artwork_digest,
)
from app.services.exact_print_approval import _narrow_by_artwork


def _png(seed: int, size=(120, 168), alpha_pad: bool = False) -> bytes:
    """A deterministic, visually distinctive card-like image."""
    from PIL import Image, ImageDraw

    w, h = size
    img = Image.new("RGBA" if alpha_pad else "RGB", (w * 2, h * 2) if alpha_pad else (w, h),
                    (0, 0, 0, 0) if alpha_pad else (255, 255, 255))
    canvas = Image.new("RGB", (w, h), (250, 250, 250))
    d = ImageDraw.Draw(canvas)
    rng = seed
    for i in range(14):
        rng = (rng * 1103515245 + 12345) % 2147483648
        x0 = rng % w; y0 = (rng // 7) % h
        x1 = min(w, x0 + 12 + (rng // 13) % 60); y1 = min(h, y0 + 12 + (rng // 17) % 70)
        d.rectangle([x0, y0, x1, y1], fill=((rng * 37) % 256, (rng * 91) % 256, (rng * 53) % 256))
    if alpha_pad:
        img.paste(canvas.convert("RGBA"), (w // 2, h // 2))
        out = img
    else:
        out = canvas
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


# --- the ranking module ------------------------------------------------------


def test_digest_is_stable_and_ignores_transport_padding():
    """The same artwork through SNKRDUNK's background-removed padding must
    normalise to the same class as the unpadded original."""
    plain = _png(7)
    padded = _png(7, alpha_pad=True)
    assert official_artwork_digest(plain) == official_artwork_digest(padded)
    assert official_artwork_digest(plain) != official_artwork_digest(_png(8))
    assert len(official_artwork_digest(plain)) == 64


def test_exact_when_one_artwork_clearly_wins():
    listing = _png(11, alpha_pad=True)
    v = evaluate_artwork(listing, {1: _png(11), 2: _png(99)})
    assert v.status == STATUS_EXACT
    assert v.card_print_id == 1
    assert v.card_print_ids_before == (1, 2)
    assert v.card_print_ids_after == (1,)
    assert v.narrowed is True
    assert v.method_version == ARTWORK_METHOD_VERSION


def test_reprints_sharing_one_artwork_stay_ambiguous():
    """The OP04-044 / OP01-120 case: an image identifies an artwork, and two
    prints of the same artwork can never be told apart by one."""
    art = _png(21)
    v = evaluate_artwork(_png(21, alpha_pad=True), {1: art, 2: art, 3: _png(77)})
    assert v.status == STATUS_AMBIGUOUS
    assert v.card_print_id is None
    assert set(v.winning_class) == {1, 2}
    assert "share one artwork" in v.detail


def test_stored_artwork_key_defines_the_class_without_reading_pixels():
    """card_prints.artwork_key is the catalogue's own SHA-256 of the official
    asset, so two prints sharing it are one class even when the bytes handed
    in differ (a re-encode, a different CDN rendition)."""
    v = evaluate_artwork(
        _png(31, alpha_pad=True),
        {1: _png(31), 2: _png(31), 3: _png(88)},
        artwork_keys={1: "shared-key", 2: "shared-key", 3: "other-key"},
    )
    assert v.status == STATUS_AMBIGUOUS
    assert set(v.winning_class) == {1, 2}


def test_no_match_when_the_photo_depicts_none_of_the_allowed_prints():
    v = evaluate_artwork(_png(500, alpha_pad=True), {1: _png(11), 2: _png(99)})
    assert v.status == STATUS_NO_MATCH
    assert v.card_print_ids_after == (1, 2)
    assert v.narrowed is False


def test_close_artworks_are_refused_on_margin_not_guessed():
    art = _png(41)
    v = evaluate_artwork(_png(41, alpha_pad=True), {1: art, 2: art},
                         artwork_keys={1: "a", 2: "b"}, margin_min=40)
    assert v.status == STATUS_AMBIGUOUS
    assert v.margin == 0


@pytest.mark.parametrize(
    "listing,officials,expected",
    [
        (None, {1: _png(1)}, "no listing image"),
        (_png(1), {}, "no official artwork"),
        (b"not-an-image", {1: _png(1)}, "could not be decoded"),
    ],
)
def test_missing_or_undecodable_input_is_unusable_never_a_match(listing, officials, expected):
    v = evaluate_artwork(listing, officials)
    assert v.status == STATUS_UNUSABLE
    assert expected in v.detail
    assert v.card_print_ids_after == v.card_print_ids_before


def test_an_unreadable_official_image_never_eliminates_its_print():
    """Absent evidence must not remove a printing from contention."""
    v = evaluate_artwork(_png(11, alpha_pad=True), {1: _png(11), 2: b"broken"})
    assert 2 in v.card_print_ids_after
    assert v.status == STATUS_AMBIGUOUS


# --- containment inside resolve_exact_print ----------------------------------


def _exact(before=(1, 2), chosen=1):
    return ArtworkVerdict(status=STATUS_EXACT, card_print_id=chosen,
                          winning_class=(chosen,), best_score=20, runner_up_score=120,
                          margin=100, card_print_ids_before=tuple(before),
                          card_print_ids_after=(chosen,))


def test_flag_off_means_artwork_is_never_consulted(monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "ARTWORK_EVIDENCE_ENABLED", False)
    ids, note = _narrow_by_artwork([1, 2], 1, _exact())
    assert ids == [1, 2]
    assert note is None


def test_flag_on_narrows_to_the_artwork_the_operator_named(monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "ARTWORK_EVIDENCE_ENABLED", True)
    ids, note = _narrow_by_artwork([1, 2], 1, _exact())
    assert ids == [1]
    assert note and "listing artwork" in note


@pytest.mark.parametrize(
    "surviving,chosen,verdict_before,operator,reason",
    [
        ([1, 2], 1, (1, 2, 3), 1, "verdict computed over a different print set"),
        ([1, 2], 3, (1, 2), 3, "chosen print already excluded elsewhere"),
        ([1, 2], 2, (1, 2), 1, "artwork disagrees with the operator"),
    ],
)
def test_flag_on_still_refuses_to_narrow_in_unsafe_shapes(
    monkeypatch, surviving, chosen, verdict_before, operator, reason
):
    from app.settings import settings

    monkeypatch.setattr(settings, "ARTWORK_EVIDENCE_ENABLED", True)
    v = ArtworkVerdict(status=STATUS_EXACT, card_print_id=chosen, winning_class=(chosen,),
                       best_score=20, runner_up_score=120, margin=100,
                       card_print_ids_before=verdict_before, card_print_ids_after=(chosen,))
    ids, note = _narrow_by_artwork(list(surviving), operator, v)
    assert ids == list(surviving), reason
    assert note is None, reason


@pytest.mark.parametrize("status", [STATUS_AMBIGUOUS, STATUS_NO_MATCH, STATUS_UNUSABLE])
def test_flag_on_ignores_every_non_exact_verdict(monkeypatch, status):
    from app.settings import settings

    monkeypatch.setattr(settings, "ARTWORK_EVIDENCE_ENABLED", True)
    v = ArtworkVerdict(status=status, card_print_ids_before=(1, 2), card_print_ids_after=(1, 2))
    ids, note = _narrow_by_artwork([1, 2], 1, v)
    assert ids == [1, 2]
    assert note is None


def test_flag_on_with_no_verdict_changes_nothing(monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "ARTWORK_EVIDENCE_ENABLED", True)
    assert _narrow_by_artwork([1, 2], 1, None) == ([1, 2], None)


def test_artwork_never_widens_a_single_survivor(monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "ARTWORK_EVIDENCE_ENABLED", True)
    ids, note = _narrow_by_artwork([1], 1, _exact(before=(1,), chosen=1))
    assert ids == [1]
    assert note is None


def test_the_flag_defaults_off():
    """Shipping this enabled would let a provisional threshold eliminate a
    printing unattended. It must be opted into."""
    from app.settings import Settings

    assert Settings().ARTWORK_EVIDENCE_ENABLED is False


def test_imagehash_is_declared_in_this_service_requirements():
    """artwork_evidence imports imagehash lazily, inside _phash.

    That means the API starts, every test passes, and the module imports
    cleanly even when the dependency is missing from the deployed image - the
    only symptom is that every verdict comes back `unusable`. That is exactly
    what happened on staging. This test pins the declaration so the failure
    cannot recur silently.
    """
    from pathlib import Path

    requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()
    assert "ImageHash" in requirements

    import imagehash  # the import artwork_evidence actually performs

    assert imagehash is not None
