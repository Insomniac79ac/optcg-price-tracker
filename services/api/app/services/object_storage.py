"""Cloudflare R2 object storage, via its S3-compatible API.

Deliberately a thin, storage-only wrapper: bucket, key, bytes, content type,
HTTP/cache metadata, object metadata, public URL. It knows nothing about
cards, card prints, sources, SNKRDUNK, Bandai, display images, image geometry
or SHA-256 verification - all of that belongs to
app.services.display_image_mirror, which will call this module in a later
tranche. Keeping the split strict is the point: this file must stay
reviewable as "does it move exactly these bytes to exactly this key", with no
domain rules mixed in.

The surface is four operations and no more - HEAD, PUT, GET, and public URL
construction. There is intentionally no delete, no list, no multipart upload,
no presigned URL, no bucket creation and no conditional-write handling. The
mirroring flow that follows needs none of them: because an object's key *is*
the SHA-256 of its content, the caller HEADs the key, PUTs the exact bytes
when absent, GETs them back and hashes to confirm. Add an operation here only
when a caller actually needs it.

Configuration and credentials
-----------------------------
All five R2_* settings are optional at the application level and are checked
only here, at the moment an R2ObjectStorage is constructed - importing this
module, starting the API, serving GET /prints and running the rest of the
test suite must all keep working with every one of them unset. A missing or
malformed setting raises R2ConfigurationError *before* any boto3 client
exists.

There is no fallback to boto3's credential chain (AWS_* environment
variables, EC2/ECS instance metadata, a shared ~/.aws/credentials profile).
Both credentials are always passed explicitly from Settings; if they are not
configured, no client is built. Silently picking up an unrelated AWS identity
would be the worst possible failure mode for a write-capable client.

Neither credential is ever stored on an R2ObjectStorage instance - the access
key id and secret are read inside from_settings(), handed straight to
boto3.client() and then go out of scope. So no attribute, repr, log line or
exception raised by this module can carry them, by construction rather than
by remembering to redact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import quote, urlparse

import boto3
from botocore.exceptions import ClientError

from app.settings import Settings
from app.settings import settings as default_settings

# Cloudflare R2's S3 API host for the default jurisdiction. The public
# delivery origin is a different host entirely and is never derived from this
# one - see public_url() and R2_PUBLIC_BASE_URL.
R2_ENDPOINT_TEMPLATE = "https://{account_id}.r2.cloudflarestorage.com"

# R2 has no meaningful regions; the S3 protocol still requires one, and
# Cloudflare's documented value is "auto".
R2_REGION = "auto"

# Loose shapes, only strict enough that a configured value cannot rewrite the
# endpoint host or the object path. Not an attempt to mirror Cloudflare's own
# validation - the bucket and token already exist by the time these are used.
_ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_BUCKET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class R2ConfigurationError(Exception):
    """R2 storage was asked for but is not (validly) configured.

    Raised before any client is constructed. Messages name the *setting* that
    is missing or malformed and never include a credential value.
    """


class InvalidObjectKey(ValueError):
    """A caller-supplied object key failed fail-closed validation."""


# --- configuration ----------------------------------------------------------


def _require_setting(value: str | None, name: str) -> str:
    if value is None or not value.strip():
        raise R2ConfigurationError(
            f"{name} is not configured. All of R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
            "R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME and R2_PUBLIC_BASE_URL must be "
            "set to use R2 object storage."
        )
    return value.strip()


def normalize_public_base_url(raw: str) -> str:
    """Validate and normalize R2_PUBLIC_BASE_URL to end in exactly one slash.

    Just enough validation to stop a malformed value producing a malformed or
    surprising public URL: https, a hostname, and no query or fragment (a
    base URL carrying either would silently corrupt every key appended to
    it). Any path prefix is kept, because a custom domain may serve the
    bucket under one.
    """
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise R2ConfigurationError(
            f"R2_PUBLIC_BASE_URL must use https, got scheme {parsed.scheme!r}."
        )
    if not parsed.hostname:
        raise R2ConfigurationError("R2_PUBLIC_BASE_URL must include a hostname.")
    if parsed.query:
        raise R2ConfigurationError("R2_PUBLIC_BASE_URL must not include a query string.")
    if parsed.fragment:
        raise R2ConfigurationError("R2_PUBLIC_BASE_URL must not include a fragment.")
    # rstrip then re-add, so "https://h", "https://h/" and "https://h///"
    # all normalize to the same single-slash form.
    return raw.strip().rstrip("/") + "/"


# --- key safety -------------------------------------------------------------


def validate_object_key(key: str) -> str:
    """Fail-closed check on an object key, returned unchanged when it passes.

    R2 keys are opaque strings, not filesystem paths, so this rejects
    obviously bad input and then leaves the key completely alone - no
    normalization, no re-encoding, no case folding, and deliberately no URL
    decoding before validation (decoding first would let "%2e%2e" smuggle a
    ".." segment past the check and then be stored under a different key than
    the caller asked for).

    Keys here look like ``display-images/sha256/00/<64 hex>.webp``.
    """
    if not isinstance(key, str) or not key:
        raise InvalidObjectKey("Object key must be a non-empty string.")
    if key.startswith("/"):
        raise InvalidObjectKey(f"Object key must not start with '/': {key!r}")
    if "\\" in key:
        raise InvalidObjectKey(f"Object key must not contain a backslash: {key!r}")
    if any(segment == ".." for segment in key.split("/")):
        raise InvalidObjectKey(f"Object key must not contain a '..' segment: {key!r}")
    if any(ch == "\x7f" or ord(ch) < 0x20 for ch in key):
        raise InvalidObjectKey("Object key must not contain control characters.")
    return key


def _validated_metadata(metadata: Mapping[str, Any] | None) -> dict[str, str]:
    """S3 user metadata is a string->string map. Reject anything else rather
    than coercing: an int silently becoming "1" is the kind of thing that
    only shows up much later, in stored object metadata nobody re-reads."""
    if not metadata:
        return {}
    validated: dict[str, str] = {}
    for name, value in metadata.items():
        if not isinstance(name, str) or not name:
            raise ValueError(f"Object metadata keys must be non-empty strings, got {name!r}.")
        if not isinstance(value, str):
            raise ValueError(
                f"Object metadata values must be strings; {name!r} is {type(value).__name__}."
            )
        validated[name] = value
    return validated


# --- results ----------------------------------------------------------------


@dataclass(frozen=True)
class ObjectHead:
    """What HEAD told us about an existing object, and nothing more.

    Existence is carried by the return type itself - head_object() returns
    None when the object genuinely does not exist, so an `exists` flag here
    would be a second, redundant source of the same truth.

    `etag` is retained verbatim as an opaque server-assigned token. It is
    *not* an MD5 and *not* a SHA-256; nothing in this module or its callers
    may treat it as a content digest. Content verification is done by hashing
    the bytes returned from get_object_bytes(), in the mirroring layer.
    """

    key: str
    content_length: int | None = None
    content_type: str | None = None
    cache_control: str | None = None
    etag: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


# --- client -----------------------------------------------------------------


def _is_not_found(error: ClientError) -> bool:
    """True only for a genuine object-not-found. Auth failures, permission
    failures, throttling and server errors must never land here - they
    propagate, so a misconfigured token can't be mistaken for an empty
    bucket and re-uploaded over."""
    response = error.response or {}
    code = str((response.get("Error") or {}).get("Code", ""))
    status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404


class R2ObjectStorage:
    """Byte-level access to one R2 bucket.

    Construct with from_settings(); the (client, bucket_name,
    public_base_url) constructor exists so tests can inject a fake client
    without any configuration or network at all. No client is created at
    module import - importing this module never requires R2 configuration.
    """

    def __init__(self, *, client: Any, bucket_name: str, public_base_url: str) -> None:
        self._client = client
        self.bucket_name = bucket_name
        # Already normalized by from_settings(); normalize again so a
        # directly-constructed instance behaves identically.
        self.public_base_url = normalize_public_base_url(public_base_url)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "R2ObjectStorage":
        """Validate configuration, then build the boto3 client explicitly.

        Every check happens before boto3 is touched, so a misconfigured
        deployment fails with a named setting rather than a confusing
        credential-chain or DNS error.
        """
        cfg = settings if settings is not None else default_settings

        account_id = _require_setting(cfg.R2_ACCOUNT_ID, "R2_ACCOUNT_ID")
        access_key_id = _require_setting(cfg.R2_ACCESS_KEY_ID, "R2_ACCESS_KEY_ID")
        secret_access_key = _require_setting(cfg.R2_SECRET_ACCESS_KEY, "R2_SECRET_ACCESS_KEY")
        bucket_name = _require_setting(cfg.R2_BUCKET_NAME, "R2_BUCKET_NAME")
        public_base_url = normalize_public_base_url(
            _require_setting(cfg.R2_PUBLIC_BASE_URL, "R2_PUBLIC_BASE_URL")
        )

        if not _ACCOUNT_ID_RE.match(account_id):
            raise R2ConfigurationError(
                "R2_ACCOUNT_ID must be alphanumeric (with - or _); it is interpolated "
                "into the R2 API hostname."
            )
        if not _BUCKET_NAME_RE.match(bucket_name):
            raise R2ConfigurationError("R2_BUCKET_NAME is not a valid bucket name.")

        client = boto3.client(
            service_name="s3",
            endpoint_url=R2_ENDPOINT_TEMPLATE.format(account_id=account_id),
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=R2_REGION,
        )
        return cls(client=client, bucket_name=bucket_name, public_base_url=public_base_url)

    def __repr__(self) -> str:
        # Bucket, and nothing that could be a credential. Explicit rather
        # than default, so adding a secret attribute later can't leak here.
        return f"<R2ObjectStorage bucket={self.bucket_name!r}>"

    # --- operations ---------------------------------------------------------

    def head_object(self, key: str) -> ObjectHead | None:
        """Metadata for `key`, or None if the object genuinely doesn't exist.

        Every other error - authentication, permission, malformed request,
        server failure - propagates as botocore's ClientError.
        """
        key = validate_object_key(key)
        try:
            response = self._client.head_object(Bucket=self.bucket_name, Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                return None
            raise
        return ObjectHead(
            key=key,
            content_length=response.get("ContentLength"),
            content_type=response.get("ContentType"),
            cache_control=response.get("CacheControl"),
            etag=response.get("ETag"),
            metadata=dict(response.get("Metadata") or {}),
        )

    def put_object(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
        cache_control: str | None = None,
    ) -> dict[str, Any]:
        """Write `body` to `key`, byte for byte.

        The low-level PutObject call, not upload_file/upload_fileobj/the
        transfer manager: these assets are small, and the point is that the
        exact bytes handed in are the exact Body sent. Nothing here decodes,
        re-encodes, resizes, compresses, base64s, wraps in BytesIO or writes
        to disk - callers content-address their objects by the SHA-256 of
        these bytes, so any transformation would be a correctness bug, not
        just an inefficiency.

        No ACL, no StorageClass and no object tags are sent: the bucket's
        configured defaults apply, and mutable per-object state has no place
        under a content-addressed key.
        """
        key = validate_object_key(key)
        if not isinstance(body, (bytes, bytearray)):
            raise TypeError(f"put_object body must be bytes, got {type(body).__name__}.")

        params: dict[str, Any] = {
            "Bucket": self.bucket_name,
            "Key": key,
            "Body": bytes(body),
        }
        if content_type is not None:
            params["ContentType"] = content_type
        if cache_control is not None:
            # Passed through verbatim. Caching policy belongs to the caller -
            # this module holds no opinion about immutability or max-age.
            params["CacheControl"] = cache_control
        validated_metadata = _validated_metadata(metadata)
        if validated_metadata:
            params["Metadata"] = validated_metadata

        return self._client.put_object(**params)

    def get_object_bytes(self, key: str) -> bytes:
        """Read `key` back in full, as raw bytes.

        No decoding to text, no image inspection, no hashing - verification
        is the caller's job. The streaming body is always closed, including
        on a read failure, so a connection is never leaked back to the pool.

        Errors, including a missing object, propagate. There is no None
        return here on purpose: callers HEAD first, so an object vanishing
        between HEAD and GET is a real anomaly and must not be quietly
        flattened into "absent".
        """
        key = validate_object_key(key)
        response = self._client.get_object(Bucket=self.bucket_name, Key=key)
        body = response["Body"]
        try:
            return body.read()
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()

    def public_url(self, key: str) -> str:
        """The public delivery URL for `key`.

        Built from R2_PUBLIC_BASE_URL, which is authoritative - never from
        the S3 API endpoint, and never by asking R2. The bucket name is not
        appended: an r2.dev URL or custom domain already resolves to one
        bucket.

        Plain concatenation onto the single-trailing-slash base, rather than
        urljoin: a validated key can never start with "/" or contain a
        backslash, so it cannot replace the host or escape the base path, and
        the key's own hierarchy survives intact. Percent-encoding is applied
        with "/" kept safe, which is a no-op for the hex keys used here.
        """
        key = validate_object_key(key)
        return self.public_base_url + quote(key, safe="/")
