"""R2 object storage (app.services.object_storage).

Nothing here contacts Cloudflare, uses a real credential, or opens a socket:
every operation runs against a FakeS3Client that records the exact kwargs
boto3 would have received, and the one test that builds a *real* boto3 client
does so with obviously-fake credentials while socket.socket is blocked - which
is itself the assertion that client construction alone talks to nobody.

What these tests are really pinning:

  * Configuration is checked when storage is *constructed*, never at import
    or app startup, and never falls back to boto3's AWS credential chain. A
    missing setting names itself and no credential value appears anywhere.
  * put_object sends the caller's bytes verbatim. Byte *equality* is asserted
    (not object identity), because a re-encode that happened to round-trip
    would still be a correctness bug under content-addressed keys.
  * A HEAD 404 is the only thing that becomes None. A 403 - the shape a
    misconfigured or wrongly-scoped token takes - must propagate, or the
    mirroring layer would read "no such object" and overwrite.
  * public_url comes from R2_PUBLIC_BASE_URL, keeps the key hierarchy, and
    can't be steered off-host by the key.
"""

from __future__ import annotations

import importlib.util
import io
import socket
import sys
import tokenize
from pathlib import Path
from urllib.parse import urlparse

import boto3
import pytest
from botocore.exceptions import ClientError

from app.services import object_storage as storage_module
from app.services.object_storage import (
    R2_REGION,
    InvalidObjectKey,
    ObjectHead,
    R2ConfigurationError,
    R2ObjectStorage,
    normalize_public_base_url,
    validate_object_key,
)
from app.settings import Settings

# Obviously-fake values. The real account id, token and r2.dev host are
# configured only as runtime environment variables and appear in no file in
# this repository.
FAKE_ACCOUNT_ID = "fake-account-id"
FAKE_ACCESS_KEY_ID = "fake-access-key-id"
FAKE_SECRET_ACCESS_KEY = "fake-secret-access-key"
FAKE_BUCKET = "fake-bucket"
FAKE_PUBLIC_BASE_URL = "https://fake-public-host.r2.dev"

# The shape the mirroring tranche will use: sha256 hex, fanned out by its
# first two characters.
DIGEST = "0f" + "a1b2c3d4e5" * 6 + "0f12"
CONTENT_KEY = f"display-images/sha256/0f/{DIGEST}.webp"

IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"


def r2_settings(**overrides: str | None) -> Settings:
    values: dict[str, str | None] = {
        "R2_ACCOUNT_ID": FAKE_ACCOUNT_ID,
        "R2_ACCESS_KEY_ID": FAKE_ACCESS_KEY_ID,
        "R2_SECRET_ACCESS_KEY": FAKE_SECRET_ACCESS_KEY,
        "R2_BUCKET_NAME": FAKE_BUCKET,
        "R2_PUBLIC_BASE_URL": FAKE_PUBLIC_BASE_URL,
    }
    values.update(overrides)
    return Settings(**values)


def client_error(code: str, status: int, operation: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": f"{code} from fake R2"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        operation,
    )


class FakeBody:
    """Stands in for botocore's StreamingBody - records that it was closed."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self.closed = False
        self.read_calls = 0

    def read(self) -> bytes:
        self.read_calls += 1
        return self._data

    def close(self) -> None:
        self.closed = True


class FailingBody(FakeBody):
    def read(self) -> bytes:
        self.read_calls += 1
        raise OSError("connection reset mid-read")


class FakeS3Client:
    """Records calls; raises whatever the test queued instead."""

    def __init__(
        self,
        *,
        head_response: dict | None = None,
        head_error: Exception | None = None,
        get_body: FakeBody | None = None,
        get_error: Exception | None = None,
    ) -> None:
        self.head_calls: list[dict] = []
        self.put_calls: list[dict] = []
        self.get_calls: list[dict] = []
        self._head_response = head_response or {}
        self._head_error = head_error
        self._get_body = get_body
        self._get_error = get_error

    def head_object(self, **kwargs):
        self.head_calls.append(kwargs)
        if self._head_error is not None:
            raise self._head_error
        return self._head_response

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        return {"ETag": '"fake-etag"'}

    def get_object(self, **kwargs):
        self.get_calls.append(kwargs)
        if self._get_error is not None:
            raise self._get_error
        return {"Body": self._get_body if self._get_body is not None else FakeBody(b"")}


def make_storage(client: FakeS3Client, *, public_base_url: str = FAKE_PUBLIC_BASE_URL):
    return R2ObjectStorage(
        client=client, bucket_name=FAKE_BUCKET, public_base_url=public_base_url
    )


def storage_module_code() -> str:
    """object_storage.py with comments and string literals stripped out.

    Several tests below assert that a term never appears in the module - but
    the module's own docstring names the excluded concepts (SNKRDUNK, Pillow,
    upload_file, multipart, ...) precisely in order to say they are out of
    scope, and it should keep doing that. Tokenizing and dropping COMMENT and
    STRING tokens leaves only executable code, which is what those assertions
    are actually about.
    """
    source = Path(storage_module.__file__).read_text()
    kept: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        kept.append(token.string)
    return "\n".join(kept)


# --- configuration ----------------------------------------------------------


def test_all_five_settings_accepted(monkeypatch):
    recorded: dict = {}

    def fake_boto3_client(**kwargs):
        recorded.update(kwargs)
        return FakeS3Client()

    monkeypatch.setattr(boto3, "client", fake_boto3_client)

    store = R2ObjectStorage.from_settings(r2_settings())

    assert store.bucket_name == FAKE_BUCKET
    assert store.public_base_url == FAKE_PUBLIC_BASE_URL + "/"
    assert recorded  # a client really was built


@pytest.mark.parametrize(
    "missing",
    [
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
        "R2_PUBLIC_BASE_URL",
    ],
)
def test_each_missing_setting_is_a_named_configuration_error(monkeypatch, missing):
    """Fails before boto3 is touched - a client that got built with a missing
    credential would fall through to whatever AWS identity the environment
    happens to offer, which is exactly what must not happen."""

    def explode(**kwargs):  # pragma: no cover - must never run
        raise AssertionError("boto3.client must not be called with invalid config")

    monkeypatch.setattr(boto3, "client", explode)

    with pytest.raises(R2ConfigurationError) as exc_info:
        R2ObjectStorage.from_settings(r2_settings(**{missing: None}))

    assert missing in str(exc_info.value)


def test_blank_setting_is_treated_as_missing(monkeypatch):
    monkeypatch.setattr(boto3, "client", lambda **k: FakeS3Client())
    with pytest.raises(R2ConfigurationError) as exc_info:
        R2ObjectStorage.from_settings(r2_settings(R2_BUCKET_NAME="   "))
    assert "R2_BUCKET_NAME" in str(exc_info.value)


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://insecure-host.r2.dev",  # not https
        "ftp://fake-public-host.r2.dev",
        "https:///no-host",  # no hostname
        "https://fake-public-host.r2.dev/?v=1",  # query string
        "https://fake-public-host.r2.dev/#frag",  # fragment
        "fake-public-host.r2.dev",  # no scheme at all
    ],
)
def test_malformed_public_base_url_rejected(monkeypatch, bad_url):
    monkeypatch.setattr(boto3, "client", lambda **k: FakeS3Client())
    with pytest.raises(R2ConfigurationError):
        R2ObjectStorage.from_settings(r2_settings(R2_PUBLIC_BASE_URL=bad_url))


def test_account_id_cannot_rewrite_the_endpoint_host(monkeypatch):
    """The account id is interpolated into a hostname, so a value carrying a
    slash or an @ must be refused rather than redirecting the API endpoint."""
    monkeypatch.setattr(boto3, "client", lambda **k: FakeS3Client())
    for bad in ["evil.example.com/", "account@evil.example.com", "acct id"]:
        with pytest.raises(R2ConfigurationError):
            R2ObjectStorage.from_settings(r2_settings(R2_ACCOUNT_ID=bad))


def test_unrelated_api_code_serves_with_every_r2_setting_unset(client, db_session):
    """The whole point of the settings being optional: an API process with no
    R2 configuration at all must import, start and serve normally. The
    `client` fixture builds the full app (every router imported) against the
    process-wide settings object, where no R2_* value is ever set."""
    from app.settings import settings as live_settings

    assert live_settings.R2_ACCOUNT_ID is None
    assert live_settings.R2_ACCESS_KEY_ID is None
    assert live_settings.R2_SECRET_ACCESS_KEY is None
    assert live_settings.R2_BUCKET_NAME is None
    assert live_settings.R2_PUBLIC_BASE_URL is None

    assert client.get("/health").status_code == 200
    assert client.get("/prints").status_code == 200


def test_settings_defaults_leave_every_r2_field_unset():
    defaults = Settings()
    assert defaults.R2_ACCOUNT_ID is None
    assert defaults.R2_ACCESS_KEY_ID is None
    assert defaults.R2_SECRET_ACCESS_KEY is None
    assert defaults.R2_BUCKET_NAME is None
    assert defaults.R2_PUBLIC_BASE_URL is None


# --- client construction ----------------------------------------------------


def test_boto3_client_receives_explicit_r2_configuration(monkeypatch):
    recorded: dict = {}

    def fake_boto3_client(**kwargs):
        recorded.update(kwargs)
        return FakeS3Client()

    monkeypatch.setattr(boto3, "client", fake_boto3_client)
    R2ObjectStorage.from_settings(r2_settings())

    assert recorded["service_name"] == "s3"
    assert recorded["endpoint_url"] == f"https://{FAKE_ACCOUNT_ID}.r2.cloudflarestorage.com"
    assert recorded["region_name"] == "auto"
    assert R2_REGION == "auto"
    assert recorded["aws_access_key_id"] == FAKE_ACCESS_KEY_ID
    assert recorded["aws_secret_access_key"] == FAKE_SECRET_ACCESS_KEY
    # No positional/profile/session indirection that could reintroduce the
    # AWS credential chain.
    assert "profile_name" not in recorded


def test_no_client_is_constructed_at_module_import(monkeypatch):
    """Loads a second, independent copy of the module from source with
    boto3.client patched, so the assertion is about import itself rather than
    about whatever already happened when the test session started."""
    calls: list[dict] = []

    def recording_client(**kwargs):  # pragma: no cover - must never run
        calls.append(kwargs)
        raise AssertionError("boto3.client called during module import")

    monkeypatch.setattr(boto3, "client", recording_client)

    name = "_object_storage_import_probe"
    spec = importlib.util.spec_from_file_location(name, Path(storage_module.__file__))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # @dataclass resolves its class's module here
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)

    assert calls == []
    assert hasattr(module, "R2ObjectStorage")


def test_client_construction_opens_no_socket(monkeypatch):
    """A real boto3 client, built from fake credentials with the socket layer
    blocked: construction must not contact R2 (or anything else)."""

    def blocked(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)

    store = R2ObjectStorage.from_settings(r2_settings())
    assert store.bucket_name == FAKE_BUCKET
    # And the URL side never needs the network either.
    assert store.public_url(CONTENT_KEY).startswith(FAKE_PUBLIC_BASE_URL)


def test_credentials_never_appear_in_repr_or_configuration_errors(monkeypatch):
    monkeypatch.setattr(boto3, "client", lambda **k: FakeS3Client())
    store = R2ObjectStorage.from_settings(r2_settings())

    rendered = repr(store) + str(vars(store))
    assert FAKE_ACCESS_KEY_ID not in rendered
    assert FAKE_SECRET_ACCESS_KEY not in rendered

    with pytest.raises(R2ConfigurationError) as exc_info:
        R2ObjectStorage.from_settings(r2_settings(R2_BUCKET_NAME=None))
    message = str(exc_info.value)
    assert FAKE_ACCESS_KEY_ID not in message
    assert FAKE_SECRET_ACCESS_KEY not in message


# --- key safety -------------------------------------------------------------


def test_content_addressed_key_accepted_unchanged():
    assert validate_object_key(CONTENT_KEY) == CONTENT_KEY


@pytest.mark.parametrize(
    "bad_key",
    [
        "",
        "/display-images/sha256/0f/x.webp",  # leading slash
        "//display-images/x.webp",  # leading slash (protocol-relative shape)
        "display-images/../../etc/passwd",  # .. segment
        "../display-images/x.webp",
        "display-images\\sha256\\x.webp",  # backslash
        "display-images/\x00x.webp",  # NUL
        "display-images/\nx.webp",  # control character
        "display-images/\x7fx.webp",  # DEL
    ],
)
def test_bad_keys_rejected_fail_closed(bad_key):
    with pytest.raises(InvalidObjectKey):
        validate_object_key(bad_key)


def test_percent_encoded_traversal_is_not_decoded_before_validation():
    """"%2e%2e" is a legitimate literal key here and must stay literal - if it
    were decoded first it would be rejected as traversal, and worse, the
    stored key could differ from the one the caller asked for."""
    key = "display-images/%2e%2e/x.webp"
    assert validate_object_key(key) == key


def test_key_validation_runs_on_every_operation():
    client = FakeS3Client(head_response={})
    store = make_storage(client)
    for call in (
        lambda: store.head_object("/bad"),
        lambda: store.put_object("/bad", b"x"),
        lambda: store.get_object_bytes("/bad"),
        lambda: store.public_url("/bad"),
    ):
        with pytest.raises(InvalidObjectKey):
            call()
    assert client.head_calls == []
    assert client.put_calls == []
    assert client.get_calls == []


# --- public URL -------------------------------------------------------------


def test_public_url_preserves_nested_key_hierarchy():
    store = make_storage(FakeS3Client())
    assert store.public_url(CONTENT_KEY) == f"{FAKE_PUBLIC_BASE_URL}/{CONTENT_KEY}"
    assert f"/display-images/sha256/0f/{DIGEST}.webp" in store.public_url(CONTENT_KEY)


@pytest.mark.parametrize(
    "configured",
    [
        "https://fake-public-host.r2.dev",
        "https://fake-public-host.r2.dev/",
        "https://fake-public-host.r2.dev///",
    ],
)
def test_trailing_slash_normalized_to_exactly_one(configured):
    assert normalize_public_base_url(configured) == "https://fake-public-host.r2.dev/"
    store = make_storage(FakeS3Client(), public_base_url=configured)
    url = store.public_url(CONTENT_KEY)
    assert url == f"https://fake-public-host.r2.dev/{CONTENT_KEY}"
    assert "//display-images" not in url


def test_public_url_keeps_a_configured_path_prefix():
    store = make_storage(FakeS3Client(), public_base_url="https://cdn.example.com/media/")
    assert store.public_url(CONTENT_KEY) == f"https://cdn.example.com/media/{CONTENT_KEY}"


def test_public_url_is_not_derived_from_the_s3_api_endpoint(monkeypatch):
    monkeypatch.setattr(boto3, "client", lambda **k: FakeS3Client())
    store = R2ObjectStorage.from_settings(r2_settings())
    url = store.public_url(CONTENT_KEY)
    assert "r2.cloudflarestorage.com" not in url
    assert FAKE_ACCOUNT_ID not in url
    # The bucket name is not appended - the public origin already maps to it.
    assert f"/{FAKE_BUCKET}/" not in url


def test_key_cannot_replace_the_public_hostname():
    """A key that looks like an absolute (or protocol-relative) URL must stay
    a key. urljoin would happily resolve "//evil.example.com/x" to a
    different host; appending to the normalized base cannot."""
    store = make_storage(FakeS3Client())
    for hostile_key in ["https://evil.example.com/x.webp", "evil.example.com/x.webp"]:
        url = store.public_url(hostile_key)
        assert urlparse(url).hostname == "fake-public-host.r2.dev"
        assert url.startswith(f"{FAKE_PUBLIC_BASE_URL}/")
    # The protocol-relative form never even gets that far - leading "/".
    with pytest.raises(InvalidObjectKey):
        store.public_url("//evil.example.com/x.webp")


# --- HEAD -------------------------------------------------------------------


def test_head_object_sends_exact_bucket_and_key():
    client = FakeS3Client(head_response={"ContentLength": 3})
    make_storage(client).head_object(CONTENT_KEY)
    assert client.head_calls == [{"Bucket": FAKE_BUCKET, "Key": CONTENT_KEY}]


def test_head_object_returns_existing_object_metadata():
    client = FakeS3Client(
        head_response={
            "ContentLength": 12345,
            "ContentType": "image/webp",
            "CacheControl": IMMUTABLE_CACHE_CONTROL,
            "ETag": '"d41d8cd98f00b204e9800998ecf8427e"',
            "Metadata": {"sha256": DIGEST},
        }
    )
    head = make_storage(client).head_object(CONTENT_KEY)

    assert isinstance(head, ObjectHead)
    assert head.key == CONTENT_KEY
    assert head.content_length == 12345
    assert head.content_type == "image/webp"
    assert head.cache_control == IMMUTABLE_CACHE_CONTROL
    assert head.metadata == {"sha256": DIGEST}


def test_head_object_returns_none_for_genuine_not_found():
    for code, status in [("404", 404), ("NoSuchKey", 404), ("NotFound", 404)]:
        client = FakeS3Client(head_error=client_error(code, status, "HeadObject"))
        assert make_storage(client).head_object(CONTENT_KEY) is None


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("AccessDenied", 403),
        ("InvalidAccessKeyId", 403),
        ("SignatureDoesNotMatch", 403),
        ("InternalError", 500),
        ("ServiceUnavailable", 503),
        ("SlowDown", 503),
        ("InvalidRequest", 400),
    ],
)
def test_head_object_propagates_auth_permission_and_server_errors(code, status):
    """A wrongly-scoped token answers 403, not 404. Swallowing that into None
    would tell the mirroring layer the bucket is empty."""
    client = FakeS3Client(head_error=client_error(code, status, "HeadObject"))
    with pytest.raises(ClientError) as exc_info:
        make_storage(client).head_object(CONTENT_KEY)
    assert exc_info.value.response["Error"]["Code"] == code


def test_etag_is_opaque_and_never_interpreted_as_a_digest():
    """ETag is a server-assigned token - not MD5, not SHA-256. It is carried
    through verbatim and nothing in the module compares it to anything."""
    etag = '"an-r2-assigned-token-not-a-hash"'
    client = FakeS3Client(head_response={"ETag": etag})
    head = make_storage(client).head_object(CONTENT_KEY)
    assert head.etag == etag

    lowered = storage_module_code().lower()
    for forbidden in ("etag.strip", "etag.replace", "md5", "hashlib", "sha256("):
        assert forbidden not in lowered, f"{forbidden!r} suggests ETag/digest interpretation"


# --- PUT --------------------------------------------------------------------


def test_put_object_sends_the_exact_bytes_unchanged():
    body = bytes(range(256)) * 4 + b"RIFF\x00\x00\x00\x00WEBP"
    client = FakeS3Client()
    make_storage(client).put_object(CONTENT_KEY, body)

    sent = client.put_calls[0]["Body"]
    assert isinstance(sent, bytes)
    assert sent == body  # byte equality, not object identity
    assert len(sent) == len(body)


def test_put_object_sends_exact_key_bucket_content_type_cache_control_and_metadata():
    client = FakeS3Client()
    make_storage(client).put_object(
        CONTENT_KEY,
        b"bytes",
        content_type="image/webp",
        cache_control=IMMUTABLE_CACHE_CONTROL,
        metadata={"sha256": DIGEST, "source": "mirror"},
    )

    call = client.put_calls[0]
    assert call["Bucket"] == FAKE_BUCKET
    assert call["Key"] == CONTENT_KEY
    assert call["ContentType"] == "image/webp"
    assert call["CacheControl"] == IMMUTABLE_CACHE_CONTROL
    assert call["Metadata"] == {"sha256": DIGEST, "source": "mirror"}


def test_put_object_omits_optional_parameters_when_not_supplied():
    client = FakeS3Client()
    make_storage(client).put_object(CONTENT_KEY, b"bytes")
    call = client.put_calls[0]
    assert set(call) == {"Bucket", "Key", "Body"}


def test_put_object_adds_no_acl_storage_class_or_tags():
    client = FakeS3Client()
    make_storage(client).put_object(
        CONTENT_KEY, b"bytes", content_type="image/webp", cache_control="public"
    )
    call = client.put_calls[0]
    for unwanted in ("ACL", "StorageClass", "Tagging", "ServerSideEncryption"):
        assert unwanted not in call


def test_put_object_rejects_non_string_metadata_values():
    client = FakeS3Client()
    store = make_storage(client)
    with pytest.raises(ValueError):
        store.put_object(CONTENT_KEY, b"bytes", metadata={"bytes": 1234})
    with pytest.raises(ValueError):
        store.put_object(CONTENT_KEY, b"bytes", metadata={"none": None})
    assert client.put_calls == []


def test_put_object_rejects_non_bytes_body():
    client = FakeS3Client()
    with pytest.raises(TypeError):
        make_storage(client).put_object(CONTENT_KEY, "not bytes")  # type: ignore[arg-type]
    assert client.put_calls == []


def test_put_object_uses_no_transfer_manager_or_byte_transformation():
    """Static guard on the module's executable code: the low-level PutObject
    call is the whole point, and no image/compression/encoding step may creep
    in."""
    code = storage_module_code()
    for forbidden in (
        "upload_file",
        "upload_fileobj",
        "TransferConfig",
        "create_multipart_upload",
        "BytesIO",
        "b64encode",
        "gzip",
        "PIL",
        "Image",
        ".encode(",
        ".decode(",
    ):
        assert forbidden not in code, f"{forbidden!r} must not appear in object_storage.py"


# --- GET --------------------------------------------------------------------


def test_get_object_bytes_sends_exact_bucket_and_key_and_returns_raw_bytes():
    payload = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
    body = FakeBody(payload)
    client = FakeS3Client(get_body=body)

    result = make_storage(client).get_object_bytes(CONTENT_KEY)

    assert client.get_calls == [{"Bucket": FAKE_BUCKET, "Key": CONTENT_KEY}]
    assert isinstance(result, bytes)
    assert result == payload


def test_get_object_bytes_closes_the_streaming_body():
    body = FakeBody(b"payload")
    make_storage(FakeS3Client(get_body=body)).get_object_bytes(CONTENT_KEY)
    assert body.closed is True
    assert body.read_calls == 1


def test_get_object_bytes_closes_the_body_even_when_the_read_fails():
    body = FailingBody(b"")
    with pytest.raises(OSError):
        make_storage(FakeS3Client(get_body=body)).get_object_bytes(CONTENT_KEY)
    assert body.closed is True


@pytest.mark.parametrize(
    ("code", "status"),
    [("AccessDenied", 403), ("InternalError", 500), ("NoSuchKey", 404)],
)
def test_get_object_bytes_propagates_storage_errors(code, status):
    """Including NoSuchKey: callers HEAD first, so an object disappearing
    between HEAD and GET is an anomaly, not an "absent" result."""
    client = FakeS3Client(get_error=client_error(code, status, "GetObject"))
    with pytest.raises(ClientError):
        make_storage(client).get_object_bytes(CONTENT_KEY)


def test_get_object_bytes_does_not_hash_or_decode_the_body():
    """Bytes that are neither valid UTF-8 nor a valid image round-trip fine -
    proof the module never decodes or inspects what it read."""
    payload = b"\xff\xfe\x00\x01not-utf8-not-an-image\x80\x81"
    result = make_storage(FakeS3Client(get_body=FakeBody(payload))).get_object_bytes(
        CONTENT_KEY
    )
    assert result == payload


# --- scope ------------------------------------------------------------------


def test_module_contains_no_domain_knowledge():
    """Storage-only: card, print, source and display-image concepts belong to
    app.services.display_image_mirror, not here."""
    code = storage_module_code().lower()
    for forbidden in (
        "card_print",
        "canonical_card",
        "snkrdunk",
        "bandai",
        "yuyutei",
        "yuyu-tei",
        "source_card_mapping",
        "bbox",
        "geometry",
        "owned_asset",
    ):
        assert forbidden not in code, f"{forbidden!r} must not appear in object_storage.py"


def test_module_performs_no_database_or_http_work():
    """No DB write is possible from here, and no HTTP client but boto3's own -
    so nothing in this tranche can touch the persisted display-image
    evidence or fetch from a source site."""
    code = storage_module_code()
    for forbidden in ("sqlalchemy", "Session", "app.models", "httpx", "requests", "alembic"):
        assert forbidden not in code, f"{forbidden!r} must not appear in object_storage.py"


def test_no_operation_opens_a_socket(monkeypatch):
    """The full HEAD/PUT/GET/URL surface against a fake client, with the
    socket layer blocked - the tranche's guarantee that nothing here reaches
    the real bucket."""

    def blocked(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)

    client = FakeS3Client(head_response={"ContentLength": 7}, get_body=FakeBody(b"payload"))
    store = make_storage(client)

    assert store.head_object(CONTENT_KEY).content_length == 7
    store.put_object(CONTENT_KEY, b"payload", content_type="image/webp")
    assert store.get_object_bytes(CONTENT_KEY) == b"payload"
    assert store.public_url(CONTENT_KEY).startswith("https://")
