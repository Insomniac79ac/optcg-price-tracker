from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_version_returns_expected_shape():
    response = client.get("/version")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"app", "version", "git_commit", "build_time", "app_env"}
    assert body["app"] == "opcg-price-tracker"
    assert isinstance(body["version"], str) and body["version"]


def test_version_reads_env_vars_when_present(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "9.9.9")
    monkeypatch.setenv("GIT_COMMIT", "abc1234")
    monkeypatch.setenv("BUILD_TIME", "2026-01-01T00:00:00Z")

    response = client.get("/version")

    body = response.json()
    assert body["version"] == "9.9.9"
    assert body["git_commit"] == "abc1234"
    assert body["build_time"] == "2026-01-01T00:00:00Z"


def test_version_falls_back_when_env_vars_absent(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    monkeypatch.delenv("GIT_COMMIT", raising=False)
    monkeypatch.delenv("BUILD_TIME", raising=False)

    response = client.get("/version")

    body = response.json()
    assert body["git_commit"] == "unknown"
    assert body["build_time"] == "unknown"
    # Falls back to reading the repo's VERSION file when no env var is set.
    assert body["version"] != ""


def test_get_version_falls_back_safely_when_version_file_missing(monkeypatch, tmp_path):
    from app.core import version as version_module

    monkeypatch.delenv("APP_VERSION", raising=False)
    monkeypatch.setattr(version_module, "_SEARCH_ROOTS", [tmp_path])

    assert version_module.get_version() == version_module.FALLBACK_VERSION
