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
    UnusableImage,
    _normalize,
    evaluate_artwork,
    official_artwork_digest,
)
from app.services.artwork_subject import subject_bbox
from app.services.exact_print_approval import (
    REFUSAL_AMBIGUOUS,
    ExactPrintApprovalError,
    SourceEvidence,
    _narrow_by_artwork,
    resolve_exact_print,
)
from tests.test_exact_print_approval import catalogue  # noqa: F401 - fixture


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


def _canvas(objects, size=(520, 380)) -> bytes:
    """A transparent canvas with each (png_bytes, (x, y)) pasted opaquely.

    This is the shape SNKRDUNK actually ships: a fixed background-removed
    canvas with the subject somewhere inside it. Objects are placed with a gap
    between them so they are genuinely separate components rather than one
    blob - the point of the test is what happens when the canvas holds more
    than one thing.
    """
    from PIL import Image

    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    for body, position in objects:
        obj = Image.open(io.BytesIO(body)).convert("RGBA")
        opaque = Image.new("RGBA", obj.size, (0, 0, 0, 255))
        opaque.paste(obj, (0, 0))
        canvas.paste(opaque, position)
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
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


# --- subject isolation on a multi-object canvas ------------------------------
#
# Staging candidate 10 is the case these cover: its listing canvas carries the
# card AND a second item, the old crop spanned both, and the squashed card
# scored 112 - a `no_match` that was about the crop, not about artwork.


def test_a_single_object_canvas_is_cropped_exactly_as_it_always_was():
    """The compatibility guarantee. One object means the subject box IS the
    alpha bounding box, so nothing about an ordinary listing changes."""
    from PIL import Image

    body = _canvas([(_png(61), (140, 90))])
    alpha = Image.open(io.BytesIO(body)).convert("RGBA").split()[-1]
    assert subject_bbox(alpha, 520 * 380) == alpha.getbbox()
    # And the pixels that reach the hash are those of the unpadded original.
    assert _normalize(body).tobytes() == _normalize(_png(61)).tobytes()


def test_a_second_object_does_not_capture_the_crop():
    """Candidate 10's shape: the card, plus a smaller item beside it."""
    card = _png(63)
    body = _canvas([(card, (40, 90)), (_png(64, size=(70, 70)), (300, 250))])
    # The subject that reaches the hash is the card, not card-plus-item.
    assert _normalize(body).tobytes() == _normalize(card).tobytes()
    v = evaluate_artwork(body, {1: card, 2: _png(65)})
    assert v.status == STATUS_EXACT
    assert v.card_print_id == 1


def test_the_old_whole_foreground_crop_is_what_this_replaces():
    """Guards the regression itself: cropping to every opaque pixel really
    does destroy the answer, so the isolation step is load-bearing rather than
    incidental."""
    from PIL import Image

    card = _png(63)
    body = _canvas([(card, (40, 90)), (_png(64, size=(70, 70)), (300, 250))])
    whole = Image.open(io.BytesIO(body)).convert("RGBA")
    whole_foreground = whole.crop(whole.split()[-1].getbbox())
    assert whole_foreground.size != Image.open(io.BytesIO(card)).size
    assert subject_bbox(whole.split()[-1], 520 * 380) != whole.split()[-1].getbbox()


def test_compression_fringe_does_not_count_as_a_second_object():
    """A few stray pixels are dust, not an item for sale, and must not push
    the canvas onto the refusal path."""
    card = _png(66)
    body = _canvas([(card, (40, 90)), (_png(67, size=(3, 3)), (500, 370))])
    assert _normalize(body).tobytes() == _normalize(card).tobytes()


def test_two_comparable_objects_are_refused_not_guessed():
    """Two cards on one canvas: the image genuinely does not say which one is
    being sold, and picking the left one would be inventing a fact."""
    body = _canvas([(_png(71), (20, 90)), (_png(72), (330, 90))], size=(600, 400))
    with pytest.raises(UnusableImage) as excinfo:
        _normalize(body)
    assert "does not say which one" in str(excinfo.value)

    v = evaluate_artwork(body, {1: _png(71), 2: _png(73)})
    assert v.status == STATUS_UNUSABLE
    assert v.card_print_ids_after == v.card_print_ids_before
    assert "no card could be isolated" in v.detail


def test_a_fully_transparent_canvas_is_unusable_not_a_blank_comparison():
    """It used to flatten to a white rectangle and get hashed like evidence."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (400, 300), (0, 0, 0, 0)).save(buf, format="PNG")
    v = evaluate_artwork(buf.getvalue(), {1: _png(11), 2: _png(12)})
    assert v.status == STATUS_UNUSABLE
    assert "fully transparent" in v.detail
    assert v.card_print_ids_after == (1, 2)


@pytest.mark.parametrize(
    "objects,size,reason",
    [
        ([(_png(81, size=(6, 6)), (200, 150))], (520, 380), "too little to be a photographed card"),
        ([(_png(82, size=(300, 8)), (20, 150))], (520, 380), "sliver"),
    ],
)
def test_a_region_that_cannot_be_a_card_is_refused(objects, size, reason):
    with pytest.raises(UnusableImage) as excinfo:
        _normalize(_canvas(objects, size=size))
    assert reason in str(excinfo.value)


def test_an_unusable_official_image_still_never_eliminates_its_print():
    """Fail-closed has to point the safe way on the official side too: a print
    whose asset we cannot read stays in contention."""
    listing = _canvas([(_png(91), (140, 90))])
    two_objects = _canvas([(_png(92), (20, 90)), (_png(93), (330, 90))], size=(600, 400))
    v = evaluate_artwork(listing, {1: _png(91), 2: two_objects})
    assert 2 in v.card_print_ids_after
    assert v.status == STATUS_AMBIGUOUS


def test_isolating_the_subject_cannot_separate_a_reprint_pair():
    """Better preprocessing must not turn an unanswerable question into an
    answer: two prints of one artwork are still two prints of one artwork."""
    art = _png(95)
    body = _canvas([(art, (40, 90)), (_png(96, size=(70, 70)), (300, 250))])
    v = evaluate_artwork(
        body, {1: art, 2: art, 3: _png(97)}, artwork_keys={1: "k", 2: "k", 3: "other"}
    )
    assert v.status == STATUS_AMBIGUOUS
    assert set(v.winning_class) == {1, 2}
    assert v.card_print_id is None


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


def test_isolation_cannot_resurrect_a_print_the_product_evidence_excluded(catalogue, monkeypatch):
    """The containment that matters most once preprocessing gets better.

    The preview evaluates artwork over every sibling of the card code, which is
    a WIDER set than the one the resolver's product evidence leaves standing.
    So a sharper crop can now confidently name a printing the source's own
    product label already ruled out. It must change nothing: artwork only ever
    removes prints from the surviving set, and a verdict computed over a
    different set is not consulted at all.
    """
    from app.settings import settings

    monkeypatch.setattr(settings, "ARTWORK_EVIDENCE_ENABLED", True)
    prints = catalogue["prints"]
    reprint = prints["r1"]  # PRB-01, excluded by an OP-02 product label

    # A candidate-10-shaped canvas whose card is the excluded reprint's artwork.
    art = _png(101)
    listing = _canvas([(art, (40, 90)), (_png(102, size=(70, 70)), (300, 250))])
    verdict = evaluate_artwork(
        listing,
        {
            prints["base"].id: _png(103),
            prints["p1"].id: _png(104),
            prints["p2"].id: _png(105),
            reprint.id: art,
            prints["sp_p3"].id: _png(106),
        },
    )
    assert verdict.status == STATUS_EXACT
    assert verdict.card_print_id == reprint.id, "the sharper crop does name the reprint"

    with pytest.raises(ExactPrintApprovalError) as excinfo:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=prints["p2"].id,
            evidence=SourceEvidence(
                source_name="snkrdunk", card_code="OP02-013", set_code="OP-02"
            ),
            artwork=verdict,
        )
    assert excinfo.value.code == REFUSAL_AMBIGUOUS
    assert reprint.id not in excinfo.value.alternatives
    assert sorted(excinfo.value.alternatives) == sorted(
        [prints["base"].id, prints["p1"].id, prints["p2"].id]
    )


def test_the_flag_defaults_off():
    """Shipping this enabled would let a provisional threshold eliminate a
    printing unattended. It must be opted into."""
    from app.settings import Settings

    assert Settings().ARTWORK_EVIDENCE_ENABLED is False


def test_every_lazy_dependency_is_declared_in_this_service_requirements():
    """artwork_evidence imports imagehash lazily inside `_phash`, and numpy
    lazily inside `artwork_subject._foreground_regions`.

    That means the API starts, every test passes, and the module imports
    cleanly even when a dependency is missing from the deployed image - the
    only symptom is that every verdict comes back `unusable`. That is exactly
    what happened on staging with imagehash. This test pins both declarations
    so the failure cannot recur silently.
    """
    from pathlib import Path

    requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()
    assert "ImageHash" in requirements
    assert "numpy" in requirements

    import imagehash  # the imports artwork_evidence actually performs
    import numpy

    assert imagehash is not None and numpy is not None
