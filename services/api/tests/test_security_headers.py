def test_security_headers_present_on_public_endpoint(client, db_session):
    response = client.get("/cards")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
    assert response.headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_admin_endpoints_include_cache_control_no_store(client, db_session):
    response = client.get("/admin/system-check")

    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_non_admin_endpoints_do_not_get_cache_control_no_store(client, db_session):
    response = client.get("/cards")

    assert "Cache-Control" not in response.headers


def test_snkrdunk_admin_gated_path_also_gets_no_store(client, db_session):
    response = client.get("/snkrdunk/candidates")

    assert response.headers.get("Cache-Control") == "no-store"


def test_security_headers_present_on_health_endpoint(client, db_session):
    response = client.get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.status_code == 200


def test_security_headers_present_on_429_response(client, db_session, monkeypatch):
    from app.core.rate_limit import reset_rate_limits
    from app.settings import settings

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_PUBLIC_READ_PER_5M", 1)
    reset_rate_limits()

    client.get("/cards")
    response = client.get("/cards")

    assert response.status_code == 429
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"
