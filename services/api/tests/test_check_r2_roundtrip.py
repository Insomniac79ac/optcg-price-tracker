"""R2 write-roundtrip smoke test (app.check_r2_roundtrip).

Runs against a fake client that really stores what it is given, so the happy
path exercises a genuine PUT -> HEAD -> GET -> compare rather than a scripted
sequence of canned answers. No network, no credential, no real bucket.

What is pinned here:

  * Each stage fails independently and names itself, so a real failure is
    diagnosable without re-running: a rejected PUT, a HEAD that reports
    not-found or the wrong length or the wrong content type, a rejected GET,
    and bytes that come back altered are five different problems.
  * The key is fixed under system-checks/ and there is no way to point this
    command at a display-image key - the command takes no --key argument, and
    run_roundtrip refuses a key outside the prefix.
  * The payload is unique per run. A constant payload would let a stale
    object left by an earlier run satisfy the GET, verifying nothing.
  * No delete is performed or referenced anywhere.
"""

from __future__ import annotations

import hashlib
import io
import tokenize
from pathlib import Path

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app import check_r2_roundtrip as roundtrip_module
from app.check_r2_roundtrip import (
    CACHE_CONTROL,
    CONTENT_TYPE,
    EXIT_FAILED,
    EXIT_NOT_CONFIGURED,
    EXIT_OK,
    PROBE_KEY,
    PROBE_KEY_PREFIX,
    build_payload,
    main,
    run_roundtrip,
)
from app.services.object_storage import R2ObjectStorage
from app.settings import settings as live_settings
from tests.test_object_storage import (
    FAKE_ACCESS_KEY_ID,
    FAKE_BUCKET,
    FAKE_SECRET_ACCESS_KEY,
    client_error,
    make_storage,
    r2_settings,
)


class StoringFakeS3Client:
    """A fake that actually stores objects, so the roundtrip is real."""

    def __init__(self, *, put_error=None, head_error=None, get_error=None):
        self.objects: dict[str, dict] = {}
        self.put_calls: list[dict] = []
        self.head_calls: list[dict] = []
        self.get_calls: list[dict] = []
        self._put_error = put_error
        self._head_error = head_error
        self._get_error = get_error
        # Set to corrupt what comes back out, without touching what went in.
        self.corrupt_body: bytes | None = None

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        if self._put_error:
            raise self._put_error
        self.objects[kwargs["Key"]] = {
            "Body": kwargs["Body"],
            "ContentType": kwargs.get("ContentType"),
            "CacheControl": kwargs.get("CacheControl"),
            "Metadata": kwargs.get("Metadata", {}),
        }
        return {"ETag": '"fake-etag"'}

    def head_object(self, **kwargs):
        self.head_calls.append(kwargs)
        if self._head_error:
            raise self._head_error
        stored = self.objects.get(kwargs["Key"])
        if stored is None:
            raise client_error("404", 404, "HeadObject")
        return {
            "ContentLength": len(stored["Body"]),
            "ContentType": stored["ContentType"],
            "CacheControl": stored["CacheControl"],
            "ETag": '"fake-etag"',
            "Metadata": stored["Metadata"],
        }

    def get_object(self, **kwargs):
        self.get_calls.append(kwargs)
        if self._get_error:
            raise self._get_error
        stored = self.objects.get(kwargs["Key"])
        if stored is None:
            raise client_error("NoSuchKey", 404, "GetObject")
        body = self.corrupt_body if self.corrupt_body is not None else stored["Body"]
        return {"Body": _Body(body)}


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.closed = False

    def read(self) -> bytes:
        return self._data

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def r2_configured(monkeypatch):
    values = r2_settings()
    for name in (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
        "R2_PUBLIC_BASE_URL",
    ):
        monkeypatch.setattr(live_settings, name, getattr(values, name))
    return values


# --- payload and key --------------------------------------------------------


def test_payload_is_unique_per_run():
    """A constant payload would pass by reading back a previous run's object,
    proving nothing about this run's write."""
    assert build_payload() != build_payload()


def test_payload_is_small_utf8_text_with_no_card_data():
    payload = build_payload()
    text = payload.decode("utf-8")
    assert len(payload) < 400
    assert "roundtrip probe" in text
    assert "safe to delete" in text


def test_probe_key_is_fixed_under_system_checks():
    assert PROBE_KEY == "system-checks/r2-roundtrip-probe.txt"
    assert PROBE_KEY.startswith(PROBE_KEY_PREFIX) and PROBE_KEY_PREFIX == "system-checks/"
    assert "display-image" not in PROBE_KEY


@pytest.mark.parametrize(
    "bad_key",
    [
        "display-images/sha256/0f/abc.webp",
        "other/probe.txt",
        "system-checks-but-not-really/probe.txt",
    ],
)
def test_keys_outside_the_prefix_are_refused(bad_key):
    client = StoringFakeS3Client()
    with pytest.raises(ValueError):
        run_roundtrip(make_storage(client), b"payload", bad_key)
    assert client.put_calls == []


def test_command_exposes_no_key_argument():
    """No invocation may point this at a production object."""
    with pytest.raises(SystemExit):
        main(["--key", "display-images/x.webp"])


# --- the happy path ---------------------------------------------------------


def test_full_roundtrip_succeeds_and_verifies_bytes():
    client = StoringFakeS3Client()
    payload = build_payload()

    result = run_roundtrip(make_storage(client), payload)

    assert result.ok is True
    assert result.exit_code == EXIT_OK
    assert result.failed_stage is None
    assert [s.name for s in result.stages] == ["put", "head", "get", "verify"]
    assert all(s.ok for s in result.stages)
    assert result.sent_sha256 == hashlib.sha256(payload).hexdigest()
    assert result.returned_sha256 == result.sent_sha256
    assert result.sent_bytes == result.returned_bytes == len(payload)


def test_put_sends_the_exact_payload_key_content_type_and_cache_control():
    client = StoringFakeS3Client()
    payload = build_payload()

    run_roundtrip(make_storage(client), payload)

    call = client.put_calls[0]
    assert call["Bucket"] == FAKE_BUCKET
    assert call["Key"] == PROBE_KEY
    assert call["Body"] == payload
    assert call["ContentType"] == CONTENT_TYPE == "text/plain"
    assert call["CacheControl"] == CACHE_CONTROL == "no-store"


def test_head_and_get_target_the_same_key_that_was_written():
    client = StoringFakeS3Client()
    run_roundtrip(make_storage(client), build_payload())
    assert client.head_calls[0] == {"Bucket": FAKE_BUCKET, "Key": PROBE_KEY}
    assert client.get_calls[0] == {"Bucket": FAKE_BUCKET, "Key": PROBE_KEY}


# --- staged failures --------------------------------------------------------


def test_put_failure_stops_the_run_and_names_the_stage():
    client = StoringFakeS3Client(put_error=client_error("AccessDenied", 403, "PutObject"))
    result = run_roundtrip(make_storage(client), build_payload())

    assert result.failed_stage == "put"
    assert result.exit_code == EXIT_FAILED
    assert "AccessDenied" in result.stages[0].detail
    assert client.head_calls == [] and client.get_calls == []


def test_put_connection_failure_is_reported():
    client = StoringFakeS3Client(
        put_error=EndpointConnectionError(endpoint_url="https://wrong.example.com")
    )
    result = run_roundtrip(make_storage(client), build_payload())
    assert result.failed_stage == "put"
    assert "EndpointConnectionError" in result.stages[0].detail


def test_head_reporting_not_found_after_a_successful_put_fails():
    """The write was accepted but the object isn't there - a silent-write
    failure, and exactly the thing a smoke test must not shrug off."""
    client = StoringFakeS3Client()

    def accept_but_discard(**kwargs):
        client.put_calls.append(kwargs)
        return {"ETag": '"fake-etag"'}  # never stored

    client.put_object = accept_but_discard
    result = run_roundtrip(make_storage(client), build_payload())

    assert result.failed_stage == "head"
    assert "not-found" in result.stages[1].detail
    assert client.get_calls == []


def test_head_length_mismatch_fails():
    client = StoringFakeS3Client()
    payload = build_payload()
    storage = make_storage(client)

    real_head = client.head_object

    def short_head(**kwargs):
        response = real_head(**kwargs)
        response["ContentLength"] = 1
        return response

    client.head_object = short_head
    result = run_roundtrip(storage, payload)

    assert result.failed_stage == "head"
    assert "content length mismatch" in result.stages[1].detail
    assert client.get_calls == []


def test_head_content_type_mismatch_fails():
    client = StoringFakeS3Client()
    storage = make_storage(client)
    real_head = client.head_object

    def wrong_type(**kwargs):
        response = real_head(**kwargs)
        response["ContentType"] = "application/octet-stream"
        return response

    client.head_object = wrong_type
    result = run_roundtrip(storage, build_payload())

    assert result.failed_stage == "head"
    assert "content type mismatch" in result.stages[1].detail


def test_get_failure_names_the_get_stage():
    client = StoringFakeS3Client(get_error=client_error("AccessDenied", 403, "GetObject"))
    result = run_roundtrip(make_storage(client), build_payload())

    assert result.failed_stage == "get"
    assert "AccessDenied" in result.stages[2].detail


def test_altered_bytes_fail_the_verify_stage():
    """The check that matters: storage that returns *something* is not the
    same as storage that returns exactly what it was given."""
    client = StoringFakeS3Client()
    payload = build_payload()
    client.corrupt_body = payload + b"tampered"

    result = run_roundtrip(make_storage(client), payload)

    assert result.failed_stage == "verify"
    assert result.exit_code == EXIT_FAILED
    assert result.returned_sha256 != result.sent_sha256
    assert "SHA-256 mismatch" in result.stages[3].detail


def test_single_flipped_byte_is_caught():
    client = StoringFakeS3Client()
    payload = build_payload()
    flipped = bytearray(payload)
    flipped[0] ^= 0x01
    client.corrupt_body = bytes(flipped)

    result = run_roundtrip(make_storage(client), payload)

    assert result.failed_stage == "verify"
    assert result.returned_bytes == result.sent_bytes  # same length, different bytes


# --- the command ------------------------------------------------------------


def test_main_exits_zero_and_prints_both_digests(monkeypatch, capsys, r2_configured):
    client = StoringFakeS3Client()
    monkeypatch.setattr(
        R2ObjectStorage,
        "from_settings",
        classmethod(lambda cls, s=None: make_storage(client)),
    )

    with pytest.raises(SystemExit) as exit_info:
        main([])

    out = capsys.readouterr().out
    assert exit_info.value.code == EXIT_OK
    assert "[OK] real PUT -> HEAD -> GET roundtrip verified byte-for-byte." in out
    assert PROBE_KEY in out
    assert "text/plain" in out and "no-store" in out
    stored_sha = hashlib.sha256(client.put_calls[0]["Body"]).hexdigest()
    assert out.count(stored_sha) >= 2  # sent and returned, printed separately


def test_main_exits_non_zero_and_names_the_failed_stage(monkeypatch, capsys, r2_configured):
    client = StoringFakeS3Client(put_error=client_error("AccessDenied", 403, "PutObject"))
    monkeypatch.setattr(
        R2ObjectStorage,
        "from_settings",
        classmethod(lambda cls, s=None: make_storage(client)),
    )

    with pytest.raises(SystemExit) as exit_info:
        main([])

    out = capsys.readouterr().out
    assert exit_info.value.code == EXIT_FAILED
    assert "[FAIL] roundtrip failed at stage: put" in out


def test_main_exits_two_when_unconfigured(monkeypatch, capsys):
    for name in (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
        "R2_PUBLIC_BASE_URL",
    ):
        monkeypatch.setattr(live_settings, name, None)

    with pytest.raises(SystemExit) as exit_info:
        main([])

    assert exit_info.value.code == EXIT_NOT_CONFIGURED
    assert "not configured" in capsys.readouterr().out


def test_no_credential_reaches_stdout(monkeypatch, capsys, r2_configured):
    leaky = ClientError(
        {
            "Error": {
                "Code": "InvalidAccessKeyId",
                "Message": f"Access Key {FAKE_ACCESS_KEY_ID} is invalid",
                "AWSAccessKeyId": FAKE_ACCESS_KEY_ID,
            },
            "ResponseMetadata": {"HTTPStatusCode": 403},
        },
        "PutObject",
    )
    client = StoringFakeS3Client(put_error=leaky)
    monkeypatch.setattr(
        R2ObjectStorage,
        "from_settings",
        classmethod(lambda cls, s=None: make_storage(client)),
    )

    with pytest.raises(SystemExit):
        main([])

    out = capsys.readouterr().out
    assert FAKE_ACCESS_KEY_ID not in out
    assert FAKE_SECRET_ACCESS_KEY not in out
    assert "InvalidAccessKeyId" in out


# --- scope ------------------------------------------------------------------


def module_code() -> str:
    source = Path(roundtrip_module.__file__).read_text()
    return "\n".join(
        token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type not in (tokenize.COMMENT, tokenize.STRING)
    )


def test_command_never_deletes_and_touches_no_card_or_database_code():
    code = module_code()
    for forbidden in (
        "delete_object",
        "delete_objects",
        "list_objects",
        "display_image",
        "card_print",
        "snkrdunk",
        "SessionLocal",
        "sqlalchemy",
        "public_url",  # public delivery is a later tranche
    ):
        assert forbidden not in code, f"{forbidden!r} must not appear in the roundtrip command"


def test_storage_class_still_has_no_delete():
    """This tranche must not add delete support; the smoke object stays put."""
    assert not hasattr(R2ObjectStorage, "delete_object")
    assert not hasattr(R2ObjectStorage, "delete")
