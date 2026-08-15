"""R2 read-only connectivity probe (app.check_r2_connectivity).

Every case here runs against the FakeS3Client from tests/test_object_storage.py -
no network, no credential, no real bucket. What is being pinned:

  * A 404 is the success case, and it is the *only* success case. A 403 (bad
    or wrongly-scoped token), a NoSuchBucket, a connection failure and an
    unexpectedly-present probe key all exit non-zero, because a probe that
    reported green on any of those would be worse than no probe at all.
  * The command reads. It never writes: the module contains no put/get/list/
    delete call, and the fake client records that none was made.
  * Neither credential can reach stdout. botocore's own InvalidAccessKeyId
    message quotes the access key id back at you, so the module prints only
    structured error fields, and scrub() covers the rest.
"""

from __future__ import annotations

import io
import tokenize
from pathlib import Path

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app import check_r2_connectivity as probe_module
from app.check_r2_connectivity import (
    EXIT_FAILED,
    EXIT_NOT_CONFIGURED,
    EXIT_OK,
    PROBE_KEY,
    ProbeResult,
    main,
    probe,
    scrub,
)
from app.services.object_storage import R2ObjectStorage
from tests.test_object_storage import (
    FAKE_ACCESS_KEY_ID,
    FAKE_BUCKET,
    FAKE_PUBLIC_BASE_URL,
    FAKE_SECRET_ACCESS_KEY,
    FakeS3Client,
    client_error,
    make_storage,
    r2_settings,
)


@pytest.fixture()
def r2_configured(monkeypatch):
    """Point the module-level settings at fake R2 values, so scrub() and the
    printed context have something to work with."""
    values = r2_settings()
    for name in (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
        "R2_PUBLIC_BASE_URL",
    ):
        monkeypatch.setattr(probe_module.settings, name, getattr(values, name))
    return values


# --- the success case -------------------------------------------------------


def test_not_found_is_the_success_case():
    client = FakeS3Client(head_error=client_error("404", 404, "HeadObject"))
    result = probe(make_storage(client))

    assert result.outcome == "not_found"
    assert result.exit_code == EXIT_OK
    assert result.ok is True
    assert client.head_calls == [{"Bucket": FAKE_BUCKET, "Key": PROBE_KEY}]


def test_probe_heads_the_documented_key_and_nothing_else():
    client = FakeS3Client(head_error=client_error("404", 404, "HeadObject"))
    probe(make_storage(client))

    assert PROBE_KEY == "system-checks/r2-read-probe-does-not-exist"
    assert len(client.head_calls) == 1
    assert client.put_calls == []
    assert client.get_calls == []


def test_probe_accepts_an_explicit_key():
    client = FakeS3Client(head_error=client_error("404", 404, "HeadObject"))
    probe(make_storage(client), "system-checks/another-probe")
    assert client.head_calls[0]["Key"] == "system-checks/another-probe"


# --- the failure cases ------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("AccessDenied", 403),
        ("InvalidAccessKeyId", 403),
        ("SignatureDoesNotMatch", 403),
        ("NoSuchBucket", 404),
        ("InternalError", 500),
        ("ServiceUnavailable", 503),
    ],
)
def test_storage_errors_fail_clearly_and_non_zero(code, status):
    """A 403 must never be mistaken for "the object isn't there" - that is the
    whole failure mode this probe exists to catch."""
    client = FakeS3Client(head_error=client_error(code, status, "HeadObject"))
    result = probe(make_storage(client))

    assert result.outcome == "storage_error"
    assert result.exit_code == EXIT_FAILED
    assert result.ok is False
    assert result.error_code == code
    assert result.http_status == status
    assert result.operation == "HeadObject"


def test_connection_failure_is_reported_separately():
    """A wrong account id produces an unresolvable endpoint, which never
    reaches a bucket - a different diagnosis from a rejected request."""
    client = FakeS3Client(
        head_error=EndpointConnectionError(endpoint_url="https://wrong.example.com")
    )
    result = probe(make_storage(client))

    assert result.outcome == "connection_error"
    assert result.exit_code == EXIT_FAILED
    assert "R2_ACCOUNT_ID" in result.detail


def test_unexpectedly_present_probe_key_fails():
    """Authentication worked, but the key is supposed to be absent. Green here
    would mean trusting a bucket that someone or something has written to."""
    client = FakeS3Client(
        head_response={"ContentLength": 11, "ContentType": "text/plain"}
    )
    result = probe(make_storage(client))

    assert result.outcome == "unexpectedly_present"
    assert result.exit_code == EXIT_FAILED
    assert "EXISTS" in result.detail
    # Still read-only: presence was learned from HEAD, the object was not read.
    assert client.get_calls == []


# --- credential safety ------------------------------------------------------


def test_scrub_removes_both_credentials(r2_configured):
    leaky = (
        f"The AWS Access Key Id {FAKE_ACCESS_KEY_ID} you provided does not exist "
        f"(secret {FAKE_SECRET_ACCESS_KEY})"
    )
    cleaned = scrub(leaky)
    assert FAKE_ACCESS_KEY_ID not in cleaned
    assert FAKE_SECRET_ACCESS_KEY not in cleaned
    assert cleaned.count("<redacted>") == 2


def test_scrub_is_a_noop_when_r2_is_unconfigured(monkeypatch):
    for name in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        monkeypatch.setattr(probe_module.settings, name, None)
    assert scrub("nothing to redact") == "nothing to redact"


def test_no_credential_reaches_stdout_on_an_auth_failure(
    monkeypatch, capsys, r2_configured
):
    """The realistic leak: S3's InvalidAccessKeyId response body quotes the
    access key id, and botocore puts it in str(exc). The command prints only
    structured fields, so it never appears."""
    leaky_error = ClientError(
        {
            "Error": {
                "Code": "InvalidAccessKeyId",
                "Message": (
                    f"The AWS Access Key Id {FAKE_ACCESS_KEY_ID} you provided does "
                    "not exist in our records."
                ),
                "AWSAccessKeyId": FAKE_ACCESS_KEY_ID,
            },
            "ResponseMetadata": {"HTTPStatusCode": 403},
        },
        "HeadObject",
    )
    client = FakeS3Client(head_error=leaky_error)
    monkeypatch.setattr(
        R2ObjectStorage, "from_settings", classmethod(lambda cls, s=None: make_storage(client))
    )

    with pytest.raises(SystemExit) as exit_info:
        main([])

    out = capsys.readouterr().out
    assert exit_info.value.code == EXIT_FAILED
    assert FAKE_ACCESS_KEY_ID not in out
    assert FAKE_SECRET_ACCESS_KEY not in out
    assert "InvalidAccessKeyId" in out  # the diagnosis still survives
    assert "403" in out


# --- the command --------------------------------------------------------


def test_main_exits_zero_and_reports_context_on_success(
    monkeypatch, capsys, r2_configured
):
    client = FakeS3Client(head_error=client_error("404", 404, "HeadObject"))
    monkeypatch.setattr(
        R2ObjectStorage, "from_settings", classmethod(lambda cls, s=None: make_storage(client))
    )

    with pytest.raises(SystemExit) as exit_info:
        main([])

    out = capsys.readouterr().out
    assert exit_info.value.code == EXIT_OK
    assert "[OK] not_found" in out
    assert FAKE_BUCKET in out
    assert FAKE_PUBLIC_BASE_URL in out
    assert PROBE_KEY in out
    assert "HeadObject (read-only" in out
    assert "nothing was uploaded, modified, deleted or read" in out


def test_main_exits_two_when_r2_is_not_configured(monkeypatch, capsys):
    """Unconfigured is its own exit code: a deployment that simply has no R2
    variables is a different problem from a rejected credential."""
    for name in (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
        "R2_PUBLIC_BASE_URL",
    ):
        monkeypatch.setattr(probe_module.settings, name, None)

    with pytest.raises(SystemExit) as exit_info:
        main([])

    out = capsys.readouterr().out
    assert exit_info.value.code == EXIT_NOT_CONFIGURED
    assert "not configured" in out
    assert "R2_ACCOUNT_ID" in out


def test_probe_result_ok_tracks_the_exit_code():
    assert ProbeResult(outcome="not_found", exit_code=EXIT_OK, detail="").ok is True
    assert ProbeResult(outcome="storage_error", exit_code=EXIT_FAILED, detail="").ok is False


# --- scope ------------------------------------------------------------------


def module_code() -> str:
    """The command's executable code, comments and strings stripped - its
    docstring names the operations it refuses to perform, and should keep
    doing so."""
    source = Path(probe_module.__file__).read_text()
    return "\n".join(
        token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type not in (tokenize.COMMENT, tokenize.STRING)
    )


def test_command_contains_no_write_or_read_operation():
    code = module_code()
    for forbidden in (
        "put_object",
        "get_object",
        "get_object_bytes",
        "delete_object",
        "list_objects",
        "upload_file",
    ):
        assert forbidden not in code, f"{forbidden!r} must not appear in the probe command"
    assert "head_object" in code


def test_command_touches_no_database():
    code = module_code()
    for forbidden in ("SessionLocal", "sqlalchemy", "app.models", "Session"):
        assert forbidden not in code, f"{forbidden!r} must not appear in the probe command"
