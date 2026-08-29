"""The API half of the shared-crop guarantee.

`app/services/artwork_subject.py` and the SNKRDUNK collector's copy of it are
one implementation kept in two files, because the two services are separate
deployables with separate build contexts. Both suites check the parity, so
whichever one a change is made in, its own tests catch the drift.

The second half of this file is the claim the tranche actually needs: the
matcher, the admin artwork preview and the collector all preprocess the same
source bytes into the same pixels.
"""

import importlib.util
import io
import pathlib

import pytest
from PIL import Image

from app.services import artwork_subject
from app.services.artwork_evidence import _normalize

HERE = pathlib.Path(__file__).resolve()
API_COPY = HERE.parents[1] / "app" / "services" / "artwork_subject.py"


def _collector_copy() -> pathlib.Path | None:
    for parent in HERE.parents:
        candidate = (
            parent / "services" / "snkrdunk_collector" / "snkrdunk_collector" / "artwork_subject.py"
        )
        if candidate.exists():
            return candidate
    return None


def test_the_two_copies_of_the_shared_crop_are_byte_identical():
    collector = _collector_copy()
    if collector is None:
        pytest.skip("Repo root not visible; services/snkrdunk_collector is unavailable here.")
    assert API_COPY.read_bytes() == collector.read_bytes(), (
        "artwork_subject.py has drifted between services/api and "
        "services/snkrdunk_collector - regenerate both from one source."
    )


def test_the_shared_module_carries_no_decision_thresholds():
    """ARTWORK_ACCEPT_MAX and ARTWORK_MARGIN_MIN belong to this service alone.
    If they ever move into the shared file, the collector inherits them by
    accident, and the two services' gates stop being independent."""
    exported = {name for name in dir(artwork_subject) if name.isupper()}
    assert "ARTWORK_ACCEPT_MAX" not in exported
    assert "ARTWORK_MARGIN_MIN" not in exported
    assert exported == {
        "FOREGROUND_ALPHA_MIN",
        "MAX_REGION_ASPECT",
        "MIN_REGION_CANVAS_SHARE",
        "REGION_DOMINANCE_SHARE",
        "REGION_NOISE_SHARE",
    }


# --- one crop, three callers -------------------------------------------------


def _card(seed: int, size=(374, 523)) -> Image.Image:
    from PIL import ImageDraw

    img = Image.new("RGB", size, (248, 246, 240))
    d = ImageDraw.Draw(img)
    rng = seed
    for _ in range(18):
        rng = (rng * 1103515245 + 12345) % 2147483648
        x0, y0 = rng % size[0], (rng // 7) % size[1]
        d.rectangle(
            [x0, y0, min(size[0], x0 + 40 + rng % 90), min(size[1], y0 + 40 + rng % 110)],
            fill=((rng * 37) % 256, (rng * 91) % 256, (rng * 53) % 256),
        )
    return img


def _canvas(objects, size=(856, 625)) -> bytes:
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    for img, pos in objects:
        opaque = Image.new("RGBA", img.size, (0, 0, 0, 255))
        opaque.paste(img.convert("RGBA"), (0, 0))
        canvas.paste(opaque, pos)
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def _load_collector_module():
    path = _collector_copy()
    if path is None:
        return None
    spec = importlib.util.spec_from_file_location("_collector_artwork_subject", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "objects",
    [
        [(_card(71), (241, 51))],                                   # ordinary listing
        [(_card(72), (241, 51)), (_card(73, size=(150, 150)), (660, 300))],  # mapping-49 shape
        [(_card(74), (10, 10))],                                    # against the canvas edge
    ],
    ids=["single-object", "two-object", "edge"],
)
def test_the_collector_and_the_matcher_isolate_the_same_pixels(objects):
    """The consistency claim, checked on the pixels rather than asserted in a
    comment: the same source bytes reach the same subject in both services.

    Only the crop is compared. What each service does afterwards is
    deliberately different - the matcher resizes 256x256 LANCZOS for phash16,
    the collector resizes its own way for its own hashes - and neither is
    allowed to inherit the other's thresholds."""
    collector = _load_collector_module()
    if collector is None:
        pytest.skip("Repo root not visible; services/snkrdunk_collector is unavailable here.")
    body = _canvas(objects)

    mine = artwork_subject.isolate_subject(Image.open(io.BytesIO(body)))
    theirs = collector.isolate_subject(Image.open(io.BytesIO(body)))

    assert mine.size == theirs.size
    assert mine.tobytes() == theirs.tobytes()


def test_the_preview_and_the_matcher_are_the_same_pipeline_by_construction():
    """The admin artwork preview is not a second implementation to keep in
    step: it calls `evaluate_artwork`, so it inherits `_normalize` and the
    shared crop with it. This pins that it has no preprocessing of its own."""
    import inspect

    from app.services import artwork_preview

    source = inspect.getsource(artwork_preview)
    assert "evaluate_artwork" in source
    for forbidden in ("getbbox", "isolate_subject", "subject_bbox", "resize(", "convert(\"RGB\")"):
        assert forbidden not in source, f"artwork_preview grew its own preprocessing: {forbidden}"


def test_normalize_is_the_shared_crop_plus_this_services_own_resize():
    """`_normalize` must stay a thin composition. If it grows its own cropping
    again, the collector's copy silently stops describing what the matcher
    does."""
    body = _canvas([(_card(81), (241, 51)), (_card(82, size=(150, 150)), (660, 300))])
    expected = artwork_subject.isolate_subject(Image.open(io.BytesIO(body))).resize(
        (256, 256), Image.LANCZOS
    )
    assert _normalize(body).tobytes() == expected.tobytes()
