"""Lossless, bounded RAW encoding; no network, clock, identity or price decisions.

Readers precede writers. Existing plaintext remains plaintext. A dictionary is
one older plaintext snapshot at the identical source URL, never a chain.
"""

import base64
import hashlib
import json
import re

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import object_session
import zstandard as zstd

PREFIX = "OPCG_RAW_ZSTD_V1:"
MAX_BYTES = 8 * 1024**2
STAGING_ENVIRONMENT = "05d1eac2-510d-4bd3-999e-fea9ead766b7"


class RawPayloadError(ValueError):
    pass


def sha256(body):
    return hashlib.sha256(body).hexdigest()


def encode(body, *, base_id, base_body):
    """Return an encoding only after an independent exact-byte reconstruction."""
    if type(base_id) is not int or base_id <= 0:
        raise RawPayloadError("positive immutable base required")
    if not (0 < len(body) <= MAX_BYTES and 0 < len(base_body) <= MAX_BYTES):
        raise RawPayloadError("bounded complete bodies required")
    dictionary = zstd.ZstdCompressionDict(
        base_body, dict_type=zstd.DICT_TYPE_RAWCONTENT
    )
    compressed = zstd.ZstdCompressor(
        level=3, dict_data=dictionary, write_checksum=True, threads=0
    ).compress(body)
    envelope = {
        "base_id": base_id,
        "base_sha256": sha256(base_body),
        "sha256": sha256(body),
        "byte_length": len(body),
        "data": base64.b64encode(compressed).decode("ascii"),
    }
    stored = PREFIX + json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    if (
        decode(stored, expected_hash=sha256(body), load_base=lambda _: base_body)
        != body
    ):
        raise RawPayloadError("independent reconstruction failed")
    return stored


def decode(stored, *, expected_hash, load_base):
    """Malformed, missing, oversized or corrupt evidence always fails closed."""
    try:
        if not isinstance(stored, str) or not stored.startswith(PREFIX):
            raise RawPayloadError("encoded RAW payload required")
        if len(stored) > 2 * MAX_BYTES:
            raise RawPayloadError("stored encoding exceeds bound")
        envelope = json.loads(stored[len(PREFIX) :])
        if set(envelope) != {"base_id", "base_sha256", "sha256", "byte_length", "data"}:
            raise RawPayloadError("unknown encoding fields")
        if type(envelope["base_id"]) is not int or envelope["base_id"] <= 0:
            raise RawPayloadError("invalid base identity")
        if (
            type(envelope["byte_length"]) is not int
            or not 0 < envelope["byte_length"] <= MAX_BYTES
        ):
            raise RawPayloadError("invalid expanded bound")
        for digest in (expected_hash, envelope["sha256"], envelope["base_sha256"]):
            if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
                raise RawPayloadError("invalid digest")
        if expected_hash != envelope["sha256"]:
            raise RawPayloadError("snapshot digest mismatch")
        base = load_base(envelope["base_id"])
        if not isinstance(base, bytes) or not 0 < len(base) <= MAX_BYTES:
            raise RawPayloadError("bounded plaintext base required")
        if sha256(base) != envelope["base_sha256"]:
            raise RawPayloadError("base digest mismatch")
        compressed = base64.b64decode(envelope["data"], validate=True)
        if zstd.frame_content_size(compressed) != envelope["byte_length"]:
            raise RawPayloadError("frame expanded size mismatch")
        dictionary = zstd.ZstdCompressionDict(base, dict_type=zstd.DICT_TYPE_RAWCONTENT)
        body = zstd.ZstdDecompressor(
            dict_data=dictionary, max_window_size=MAX_BYTES // 1024
        ).decompress(compressed, max_output_size=MAX_BYTES, allow_extra_data=False)
        if len(body) != envelope["byte_length"] or sha256(body) != expected_hash:
            raise RawPayloadError("reconstructed body mismatch")
        return body
    except RawPayloadError:
        raise
    except Exception as exc:
        # Error text must never include payloads, URLs, tokens or provider data.
        raise RawPayloadError(
            "RAW reconstruction failed: " + type(exc).__name__
        ) from None


class RawContentAccess:
    """ORM compatibility: callers receive original text; SQL exposes stored bytes.

    Direct SQL clients must explicitly decode an encoded value. No missing
    dictionary can become empty/no-listing evidence or initiate a source fetch.
    """

    @hybrid_property
    def raw_content(self):
        stored = self._stored_raw_content
        if not isinstance(stored, str) or not stored.startswith(PREFIX):
            return stored

        def load_base(base_id):
            if type(self.id) is not int or base_id >= self.id:
                raise RawPayloadError("base must precede captured snapshot")
            session = object_session(self)
            if session is None:
                raise RawPayloadError("attached retained-evidence reader required")
            base = session.get(type(self), base_id)
            if (
                base is None
                or base.source_id != self.source_id
                or base.source_url != self.source_url
                or base.parser_version != self.parser_version
                or not isinstance(base._stored_raw_content, str)
                or base._stored_raw_content.startswith(PREFIX)
            ):
                raise RawPayloadError("same-source plaintext dictionary required")
            body = base._stored_raw_content.encode("utf-8")
            if sha256(body) != base.content_hash:
                raise RawPayloadError("retained base hash mismatch")
            return body

        try:
            return decode(
                stored, expected_hash=self.content_hash, load_base=load_base
            ).decode("utf-8")
        except UnicodeDecodeError:
            raise RawPayloadError(
                "RAW reconstruction is not original UTF-8 text"
            ) from None

    @raw_content.setter
    def raw_content(self, value):
        # Writers still persist plaintext until a separately verified activation.
        if isinstance(value, str) and value.startswith(PREFIX):
            raise RawPayloadError("encoded storage requires the guarded writer")
        self._stored_raw_content = value

    @raw_content.expression
    def raw_content(cls):
        return cls._stored_raw_content
