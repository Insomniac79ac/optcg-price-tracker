"""R2 public delivery smoke test (app.check_r2_public_delivery).

No socket is opened anywhere in this file. The public side runs against
httpx.MockTransport, which means the *real* fetch_public_url - real client,
real headers, real trust_env setting - is what is under test, not a stub
standing in for it. The private side runs against the same storing fake S3
client the roundtrip tests use.

What is pinned here:

  * The GET is genuinely unauthenticated: no Authorization, no cookie, no S3
    signature headers, and trust_env off so an ambient proxy credential or
    ~/.netrc cannot attach one either. This is the claim the whole command
    exists to make, so it is asserted against the request that was actually
    sent.
  * Every failure mode is distinct and names itself: a 403, a 404, a 500, a
    200 with an empty body, a length mismatch, a digest mismatch, and equal
    digests over differing bytes are seven different problems.
  * The public URL comes from public_url() - i.e. from R2_PUBLIC_BASE_URL -
    and never from the S3 API endpoint; a base URL pointing at the API host
    fails before any request is made.
  * The command is read-only: no put, no delete, no list, and no database.
"""

from __future__ import annotations

import hashlib
import io
import tokenize
from pathlib import Path

import httpx
import pytest

from app import check_r2_public_delivery as public_module
from app.check_r2_public_delivery import (
    EXIT_FAILED,
    EXIT_NOT_CONFIGURED,
    EXIT_OK,
    PROBE_KEY,
    PROBE_KEY_PREFIX,
    fetch_public_url,
    main,
    run_public_delivery_check,
)
from app.services.object_storage import R2ObjectStorage
from app.settings import settings as live_settings
from tests.test_check_r2_roundtrip import StoringFakeS3Client, r2_configured  # noqa: F401
from tests.test_object_storage import (
    FAKE_ACCESS_KEY_ID,
    FAKE_PUBLIC_BASE_URL,
    FAKE_SECRET_ACCESS_KEY,
    client_error,
    make_storage,
)

PROBE_BODY = (
    b"cardpirate-atlas r2 roundtrip probe\n"
    b"written_at=2026-08-15T00:00:00+00:00\n"
    b"nonce=deadbeefdeadbeef\n"
)
PROBE_SHA256 = hashlib.sha256(PROBE_BODY).hexdigest()


# --- fakes ------------------------------------------------------------------


def storage_holding(body: bytes | None = PROBE_BODY, *, get_error=None, **kwargs):
    """Storage whose private read returns `body` (or fails)."""
    client = StoringFakeS3Client(get_error=get_error)
    if body is not None:
        client.objects[PROBE_KEY] = {
            "Body": body,
            "ContentType": "text/plain",
            "CacheControl": "no-store",
            "Metadata": {},
        }
    return make_storage(client, **kwargs), client


def mock_fetcher(
    *,
    status: int = 200,
    body: bytes = PROBE_BODY,
    headers: dict[str, str] | None = None,
    extra_request_headers: dict[str, str] | None = None,
):
    """A fetcher that drives the real fetch_public_url through MockTransport.

    `extra_request_headers` simulates something outside this module attaching
    a credential to the outgoing request - the one thing the command must
    notice about its own behaviour.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        for name, value in (extra_request_headers or {}).items():
            request.headers[name] = value
        seen.append(request)
        return httpx.Response(
            status,
            content=body,
            headers={"content-type": "text/plain", **(headers or {})},
        )

    def fetcher(url: str):
        return fetch_public_url(url, transport=httpx.MockTransport(handler))

    fetcher.requests = seen
    return fetcher


# --- the unauthenticated fetch ----------------------------------------------


def test_public_fetch_sends_no_credential_headers():
    fetcher = mock_fetcher()
    fetched = fetcher(f"{FAKE_PUBLIC_BASE_URL}/{PROBE_KEY}")

    sent = {name.lower() for name in fetched.request_headers}
    assert "authorization" not in sent
    assert "cookie" not in sent
    assert not any(name.startswith("x-amz-") for name in sent)
    assert fetched.credential_headers_sent == []
    assert fetched.body == PROBE_BODY
    assert fetched.http_status == 200


def test_public_fetch_ignores_ambient_environment_credentials(monkeypatch):
    """trust_env=False: no ~/.netrc, no proxy auth, nothing from the shell."""
    monkeypatch.setenv("NETRC", "/nonexistent/netrc")
    monkeypatch.setenv("HTTPS_PROXY", "https://user:pass@proxy.invalid:8080")

    fetcher = mock_fetcher()
    fetched = fetcher(f"{FAKE_PUBLIC_BASE_URL}/{PROBE_KEY}")

    assert fetched.credential_headers_sent == []
    assert fetched.http_status == 200


def test_public_fetch_records_the_url_it_was_given():
    fetcher = mock_fetcher()
    url = f"{FAKE_PUBLIC_BASE_URL}/{PROBE_KEY}"
    fetched = fetcher(url)

    assert str(fetcher.requests[0].url) == url
    assert fetched.final_host == "fake-public-host.r2.dev"
    assert fetched.redirected is False


# --- the happy path ---------------------------------------------------------


def test_matching_bytes_pass_all_four_stages():
    storage, client = storage_holding()
    fetcher = mock_fetcher()

    result = run_public_delivery_check(storage, fetcher=fetcher)

    assert result.ok
    assert result.exit_code == EXIT_OK
    assert [stage.name for stage in result.stages] == ["origin", "public", "private", "compare"]
    assert result.http_status == 200
    assert result.public_byte_length == result.private_byte_length == len(PROBE_BODY)
    assert result.public_sha256 == result.private_sha256 == PROBE_SHA256
    assert result.unauthenticated is True
    assert result.public_host == "fake-public-host.r2.dev"
    # The URL fetched is exactly what public_url() builds - no bucket name in it.
    assert str(fetcher.requests[0].url) == storage.public_url(PROBE_KEY)
    # Read-only: one GetObject, nothing else.
    assert client.get_calls == [{"Bucket": storage.bucket_name, "Key": PROBE_KEY}]
    assert client.put_calls == []


def test_check_reads_the_existing_roundtrip_probe_key():
    assert PROBE_KEY == "system-checks/r2-roundtrip-probe.txt"
    assert PROBE_KEY.startswith(PROBE_KEY_PREFIX)


@pytest.mark.parametrize("bad_key", ["display-images/sha256/0f/abc.webp", "anything-else.txt"])
def test_check_refuses_a_key_outside_system_checks(bad_key):
    storage, _ = storage_holding()
    with pytest.raises(ValueError):
        run_public_delivery_check(storage, key=bad_key, fetcher=mock_fetcher())


# --- public-side failures ---------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected_fragment"),
    [
        (403, "Public access (r2.dev) is most likely not enabled"),
        (404, "no object at this key"),
        (500, "server-side error"),
        (301, "only 200 is a pass"),
    ],
)
def test_non_200_fails_at_the_public_stage_and_stops(status, expected_fragment):
    storage, client = storage_holding()

    result = run_public_delivery_check(
        storage, fetcher=mock_fetcher(status=status, body=b"nope")
    )

    assert not result.ok
    assert result.failed_stage == "public"
    assert result.http_status == status
    assert expected_fragment in result.stages[-1].detail
    # Stopped: the authenticated read was never attempted.
    assert client.get_calls == []
    assert result.private_sha256 is None


def test_200_with_an_empty_body_fails():
    storage, client = storage_holding()

    result = run_public_delivery_check(storage, fetcher=mock_fetcher(body=b""))

    assert result.failed_stage == "public"
    assert "empty body" in result.stages[-1].detail
    assert client.get_calls == []


def test_a_credential_header_on_the_request_fails_even_on_a_200():
    """A 200 obtained with a credential proves nothing about public access."""
    storage, client = storage_holding()

    result = run_public_delivery_check(
        storage,
        fetcher=mock_fetcher(extra_request_headers={"Authorization": "Bearer something"}),
    )

    assert result.failed_stage == "public"
    assert result.unauthenticated is False
    assert "not an unauthenticated read" in result.stages[-1].detail
    assert client.get_calls == []


def test_a_transport_failure_fails_at_the_public_stage():
    def exploding_fetcher(url: str):
        raise httpx.ConnectError("dns failure")

    storage, _ = storage_holding()
    result = run_public_delivery_check(storage, fetcher=exploding_fetcher)

    assert result.failed_stage == "public"
    assert "ConnectError" in result.stages[-1].detail


def test_a_public_base_url_pointing_at_the_s3_api_host_fails_before_any_request():
    storage, _ = storage_holding(public_base_url="https://acct.r2.cloudflarestorage.com")
    fetcher = mock_fetcher()

    result = run_public_delivery_check(storage, fetcher=fetcher)

    assert result.failed_stage == "origin"
    assert fetcher.requests == []
    assert "not a public delivery origin" in result.stages[-1].detail


# --- private-side and comparison failures -----------------------------------


def test_a_failed_authenticated_read_fails_at_the_private_stage():
    storage, _ = storage_holding(get_error=client_error("AccessDenied", 403, "GetObject"))

    result = run_public_delivery_check(storage, fetcher=mock_fetcher())

    assert result.failed_stage == "private"
    assert "AccessDenied" in result.stages[-1].detail


def test_a_length_mismatch_fails_the_comparison():
    storage, _ = storage_holding(body=PROBE_BODY + b"extra")

    result = run_public_delivery_check(storage, fetcher=mock_fetcher())

    assert result.failed_stage == "compare"
    assert "byte length mismatch" in result.stages[-1].detail
    assert result.public_byte_length != result.private_byte_length


def test_same_length_different_bytes_fails_the_comparison():
    """The case a length check alone would miss - e.g. a transforming proxy."""
    altered = bytearray(PROBE_BODY)
    altered[-1] = altered[-1] ^ 0x20
    storage, _ = storage_holding(body=bytes(altered))

    result = run_public_delivery_check(storage, fetcher=mock_fetcher())

    assert result.failed_stage == "compare"
    assert "SHA-256 mismatch" in result.stages[-1].detail
    assert result.public_byte_length == result.private_byte_length


def test_equal_digests_over_differing_bytes_still_fails(monkeypatch):
    """Belt and braces: if hashing ever agreed on unequal bytes, fail anyway."""
    altered = bytearray(PROBE_BODY)
    altered[-1] = altered[-1] ^ 0x20
    storage, _ = storage_holding(body=bytes(altered))
    real_sha256 = hashlib.sha256
    monkeypatch.setattr(
        public_module.hashlib, "sha256", lambda data=b"": real_sha256(b"constant")
    )

    result = run_public_delivery_check(storage, fetcher=mock_fetcher())

    assert result.failed_stage == "compare"
    assert "the raw bytes differ" in result.stages[-1].detail


# --- the command ------------------------------------------------------------


def _patch_from_settings(monkeypatch, storage):
    monkeypatch.setattr(
        R2ObjectStorage, "from_settings", classmethod(lambda cls, s=None: storage)
    )


def test_main_exits_zero_and_reports_host_status_lengths_and_digests(
    monkeypatch, capsys, r2_configured  # noqa: F811
):
    storage, _ = storage_holding()
    _patch_from_settings(monkeypatch, storage)
    monkeypatch.setattr(public_module, "fetch_public_url", mock_fetcher())

    with pytest.raises(SystemExit) as exit_info:
        main([])

    out = capsys.readouterr().out
    assert exit_info.value.code == EXIT_OK
    assert "[OK] the public origin serves this bucket's real bytes" in out
    assert "fake-public-host.r2.dev" in out
    assert "status=200" in out
    assert out.count(PROBE_SHA256) >= 2  # public and private, printed separately
    assert f"{len(PROBE_BODY)} bytes" in out
    assert "auth sent: none" in out
    assert "nothing was uploaded, overwritten or deleted" in out


def test_main_exits_non_zero_and_names_the_failed_stage(
    monkeypatch, capsys, r2_configured  # noqa: F811
):
    storage, _ = storage_holding()
    _patch_from_settings(monkeypatch, storage)
    monkeypatch.setattr(public_module, "fetch_public_url", mock_fetcher(status=403, body=b""))

    with pytest.raises(SystemExit) as exit_info:
        main([])

    out = capsys.readouterr().out
    assert exit_info.value.code == EXIT_FAILED
    assert "[FAIL] public delivery check failed at stage: public" in out
    assert "403" in out


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


def test_no_credential_reaches_stdout(monkeypatch, capsys, r2_configured):  # noqa: F811
    leaky = client_error("InvalidAccessKeyId", 403, "GetObject")
    leaky.response["Error"]["Message"] = f"Access Key {FAKE_ACCESS_KEY_ID} is invalid"
    leaky.response["Error"]["AWSAccessKeyId"] = FAKE_ACCESS_KEY_ID
    storage, _ = storage_holding(get_error=leaky)
    _patch_from_settings(monkeypatch, storage)
    monkeypatch.setattr(public_module, "fetch_public_url", mock_fetcher())

    with pytest.raises(SystemExit):
        main([])

    out = capsys.readouterr().out
    assert FAKE_ACCESS_KEY_ID not in out
    assert FAKE_SECRET_ACCESS_KEY not in out
    assert "InvalidAccessKeyId" in out


# --- scope ------------------------------------------------------------------


def module_code() -> str:
    source = Path(public_module.__file__).read_text()
    return "\n".join(
        token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type not in (tokenize.COMMENT, tokenize.STRING)
    )


def test_command_is_read_only_and_touches_no_card_or_database_code():
    code = module_code()
    for forbidden in (
        "put_object",
        "delete_object",
        "delete_objects",
        "list_objects",
        "display_image",
        "card_print",
        "snkrdunk",
        "SessionLocal",
        "sqlalchemy",
    ):
        assert forbidden not in code, f"{forbidden!r} must not appear in the public-delivery command"


def test_storage_class_still_has_no_delete():
    assert not hasattr(R2ObjectStorage, "delete_object")
    assert not hasattr(R2ObjectStorage, "delete")
