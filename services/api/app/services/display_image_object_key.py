"""The content-addressed object-key rule for mirrored display images.

A leaf module on purpose: it imports nothing from this application, so both
the write side (app.services.display_image_mirror /
app.services.display_image_upload, which construct keys) and the read side
(app.services.display_image, which re-derives one to check a persisted
record against it) can share exactly this code. The mirror imports
app.services.display_image, so the read side cannot import the mirror back -
hence a third module rather than either of the two obvious homes.

There is deliberately only one function here. A key is the SHA-256 of the
object's bytes, fanned out by its first two characters, with the extension of
the *decoded* image format - and that rule must exist in exactly one place,
because the moment a reader and a writer disagree about it the reader points
at an object that does not exist.
"""

from __future__ import annotations

OBJECT_KEY_PREFIX = "display-images/sha256"

# Object-key extension -> the canonical media type an object under it carries.
# app.services.display_image_mirror.SUPPORTED_FORMATS maps Pillow's decoded
# format names onto these, so the extension/media-type pairing is stated once.
OBJECT_KEY_MEDIA_TYPES: dict[str, str] = {
    "webp": "image/webp",
    "png": "image/png",
    "jpg": "image/jpeg",
}


def object_key(sha256_hex: str, extension: str) -> str:
    """The content-addressed key for an object with this digest and format."""
    return f"{OBJECT_KEY_PREFIX}/{sha256_hex[:2]}/{sha256_hex}.{extension}"
