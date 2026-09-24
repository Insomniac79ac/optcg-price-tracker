"""Mock-only private storage and evidence archive safety controls."""
import gzip
import io
import json
from pathlib import Path
import sys
import tarfile

from botocore.exceptions import ClientError
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "services/api"))

import archive_bandai_release_evidence as archive
from app.services import private_object_storage as private


def settings():
    return private.EvidenceR2Settings("a" * 32, "fake-access", "fake-secret", archive.BUCKET)


def test_configuration_never_falls_back_to_display_or_ambient_credentials(monkeypatch):
    monkeypatch.setattr(private.boto3, "client", lambda **kwargs: pytest.fail("Client constructed without archive credentials"))
    with pytest.raises(private.R2ConfigurationError, match="EVIDENCE_R2_ACCOUNT_ID"):
        private.EvidenceR2Settings.from_environment({"R2_ACCOUNT_ID": "a" * 32, "AWS_ACCESS_KEY_ID": "fake"})


def test_malformed_account_id_is_rejected_before_client_construction(monkeypatch):
    monkeypatch.setattr(private.boto3, "client", lambda **kwargs: pytest.fail("Client constructed with invalid configuration"))
    cfg = private.EvidenceR2Settings("invalid-mock-account", "fake-access", "fake-secret", archive.BUCKET)
    with pytest.raises(private.R2ConfigurationError) as failure:
        private.PrivateR2ObjectStorage.from_settings(cfg)
    assert str(failure.value) == "EVIDENCE_R2_ACCOUNT_ID is malformed."


def test_explicit_credentials_private_surface_and_redacted_repr(monkeypatch):
    calls = []
    monkeypatch.setattr(private.boto3, "client", lambda **kwargs: calls.append(kwargs) or object())
    storage = private.PrivateR2ObjectStorage.from_settings(settings())
    assert calls[0]["aws_access_key_id"] == "fake-access"
    assert calls[0]["aws_secret_access_key"] == "fake-secret"
    assert calls[0]["region_name"] == "auto"
    for name in ("public_url", "public_base_url", "delete_object", "list_objects", "create_bucket", "presign"):
        assert not hasattr(storage, name)
    for secret in ("a" * 32, "fake-access", "fake-secret", archive.BUCKET):
        assert secret not in repr(settings()) + repr(storage)


def test_bucket_reachability_uses_only_head():
    calls = []
    class Client:
        def head_bucket(self, **kwargs):
            calls.append(kwargs)
    private.PrivateR2ObjectStorage(client=Client(), bucket_name=archive.BUCKET).head_bucket()
    assert calls == [{"Bucket": archive.BUCKET}]


@pytest.mark.parametrize("error_code,status,missing", [("NoSuchKey", 404, True), ("NoSuchBucket", 404, False), ("AccessDenied", 403, False)])
def test_only_object_not_found_becomes_absent(error_code, status, missing):
    class Client:
        def head_object(self, **kwargs):
            raise ClientError({"Error": {"Code": error_code}, "ResponseMetadata": {"HTTPStatusCode": status}}, "HeadObject")
    storage = private.PrivateR2ObjectStorage(client=Client(), bucket_name=archive.BUCKET)
    if missing:
        assert storage.head_object("evidence/key") is None
    else:
        with pytest.raises(ClientError):
            storage.head_object("evidence/key")


def test_put_is_conditional_and_get_closes_body():
    calls = []
    body = io.BytesIO(b"exact bytes")
    class Client:
        def put_object(self, **kwargs):
            calls.append(kwargs)
        def get_object(self, **kwargs):
            return {"Body": body}
    storage = private.PrivateR2ObjectStorage(client=Client(), bucket_name=archive.BUCKET)
    storage.put_object("evidence/key", b"exact bytes", metadata={"sha256": "fake"})
    assert calls[0]["Body"] == b"exact bytes" and calls[0]["IfNoneMatch"] == "*"
    assert calls[0]["CacheControl"] == "private, no-store" and "ACL" not in calls[0]
    assert storage.get_object_bytes("evidence/key") == b"exact bytes"
    assert body.closed


def mock_source(root):
    for name in archive.INDEX_FILES:
        (root / name).write_bytes(b"{}")
    (root / "raw").mkdir()
    (root / "records").mkdir()
    (root / "raw/payload.html.gz").write_bytes(gzip.compress(b"official mock", mtime=0))
    (root / "records/source.json").write_bytes(b"{}")
    (root / ".env").write_text("PRIVATE=must-not-archive")
    (root / "chronology_preview.json").write_text("do not archive previews")


def test_archive_is_deterministic_and_excludes_unrelated_files(tmp_path, monkeypatch):
    mock_source(tmp_path)
    monkeypatch.setattr(archive, "verify_bundle", lambda root: (archive.COUNTS, [{"official_code": "mock"}]))
    payload, manifest = archive.build_archive(tmp_path)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            path.touch()
    again, manifest_again = archive.build_archive(tmp_path)
    assert payload == again and manifest == manifest_again
    with tarfile.open(fileobj=io.BytesIO(payload)) as bundle:
        names = bundle.getnames()
        assert ".env" not in names and "chronology_preview.json" not in names
        assert "archive-manifest.json" in names
        assert all(m.mtime == 0 and m.uid == m.gid == 0 for m in bundle.getmembers())


@pytest.mark.parametrize("existing", [None, b"matching", b"different"])
def test_head_before_put_and_existing_conflict_is_never_overwritten(existing, monkeypatch):
    payload = b"matching"
    sha = archive.digest(payload)
    expected = {"archive_sha256": sha, "archive_size": len(payload),
                "object_key": f"official-evidence/bandai_jp/release-dates/2026-09-24/sha256/{sha}.tar.gz"}
    monkeypatch.setattr(archive, "recover_archive", lambda *args: {"result": "passed"})
    class Storage:
        bucket_name = archive.BUCKET
        calls = []
        data = existing
        def head_bucket(self):
            self.calls.append("HEAD_BUCKET")
        def head_object(self, key):
            self.calls.append("HEAD")
            return None if self.data is None else object()
        def put_object(self, key, body, **kwargs):
            self.calls.append("PUT")
            self.data = body
        def get_object_bytes(self, key):
            self.calls.append("GET")
            return self.data
    storage = Storage()
    if existing == b"different":
        with pytest.raises(ValueError, match="not overwritten"):
            archive.upload_archive(storage, payload, expected)
        assert storage.calls == ["HEAD_BUCKET", "HEAD", "GET"]
    else:
        receipt = archive.upload_archive(storage, payload, expected)
        assert receipt["get_back_sha256"] == sha
        assert storage.calls == (["HEAD_BUCKET", "HEAD", "PUT", "GET"] if existing is None
                                 else ["HEAD_BUCKET", "HEAD", "GET", "GET"])


def test_reuse_requires_a_second_matching_download(monkeypatch):
    payload = b"matching"
    sha = archive.digest(payload)
    expected = {"archive_sha256": sha, "archive_size": len(payload),
                "object_key": f"official-evidence/bandai_jp/release-dates/2026-09-24/sha256/{sha}.tar.gz"}
    monkeypatch.setattr(archive, "recover_archive", lambda *args: pytest.fail("Corrupt GET must fail before recovery"))
    class Storage:
        bucket_name = archive.BUCKET
        data = iter([payload, b"different"])
        def head_bucket(self):
            pass
        def head_object(self, key):
            return object()
        def put_object(self, *args, **kwargs):
            pytest.fail("Existing object must never be overwritten")
        def get_object_bytes(self, key):
            return next(self.data)
    with pytest.raises(ValueError, match="GET bytes differ"):
        archive.upload_archive(Storage(), payload, expected)


def test_public_asset_bucket_is_rejected_before_any_request():
    payload = b"matching"
    sha = archive.digest(payload)
    expected = {"archive_sha256": sha, "archive_size": len(payload),
                "object_key": f"official-evidence/bandai_jp/release-dates/2026-09-24/sha256/{sha}.tar.gz"}
    class Storage:
        bucket_name = "cardpirate-atlas-assets"
        def head_bucket(self):
            pytest.fail("Public asset storage must not be accessed")
    with pytest.raises(ValueError, match="dedicated staging archive"):
        archive.upload_archive(Storage(), payload, expected)


def test_recovery_checks_hash_before_opening_archive():
    with pytest.raises(ValueError, match="SHA-256"):
        archive.recover_archive(b"damaged", {"archive_size": 7, "archive_sha256": "0" * 64})


@pytest.mark.parametrize("name,kind", [("../escape", tarfile.REGTYPE), ("/absolute", tarfile.REGTYPE), ("link", tarfile.SYMTYPE)])
def test_recovery_rejects_unsafe_members(name, kind):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        member = tarfile.TarInfo(name)
        member.type = kind
        member.linkname = "../escape" if kind == tarfile.SYMTYPE else ""
        bundle.addfile(member)
    payload = buffer.getvalue()
    with pytest.raises(ValueError, match="Unsafe archive member"):
        archive.recover_archive(payload, {"archive_size": len(payload), "archive_sha256": archive.digest(payload), "file_count": 1})


def test_independent_recovery_has_no_source_directory_dependency(tmp_path, monkeypatch):
    mock_source(tmp_path)
    mapping = [{"official_code": "mock"}]
    monkeypatch.setattr(archive, "verify_bundle", lambda root: (archive.COUNTS, mapping))
    payload, manifest = archive.build_archive(tmp_path)
    called = []
    def recovered_only(root):
        assert root != tmp_path
        assert (root / "raw/payload.html.gz").exists()
        called.append(root)
        return archive.COUNTS, mapping
    monkeypatch.setattr(archive, "verify_bundle", recovered_only)
    result = archive.recover_archive(payload, manifest)
    assert result["source_directory_used"] is False and len(called) == 1
    assert not called[0].exists()
