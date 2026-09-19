import inspect

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.main import app
from app.models import Card, SearchHistory, User
from app.services import search as search_service
from app.services.search import (
    SEARCH_HEALTH_EXCLUDED_PROVIDERS,
    SearchHealthProbeResult,
    search,
    search_health_probe,
)


def test_search_health_probe_succeeds_on_empty_catalogue(db_session):
    before_users = db_session.query(User).count()

    result = search_health_probe(db_session)

    assert result == SearchHealthProbeResult(
        ok=True,
        providers_checked=("cards",),
        providers_skipped=SEARCH_HEALTH_EXCLUDED_PROVIDERS,
        result_count=0,
    )
    assert db_session.query(User).count() == before_users
    assert db_session.query(SearchHistory).count() == 0


def test_search_health_probe_succeeds_with_catalogue_result(db_session):
    db_session.add(
        Card(
            card_code="HEALTH-001",
            name_en="System-check",
            set_code="HEALTH",
            rarity="C",
            language="en",
        )
    )
    db_session.commit()

    result = search_health_probe(db_session)

    assert result.ok is True
    assert result.result_count == 1
    assert result.error is None


def test_search_health_probe_reports_catalogue_provider_error(
    db_session, monkeypatch
):
    def fail_catalogue_provider(*_args, **_kwargs):
        raise RuntimeError("catalogue unavailable")

    monkeypatch.setattr(search_service, "_search_cards", fail_catalogue_provider)

    result = search_health_probe(db_session)

    assert result.ok is False
    assert result.result_count == 0
    assert result.error == "RuntimeError: catalogue unavailable"


def test_search_health_probe_never_invokes_user_or_private_providers(
    db_session, monkeypatch
):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("user/private provider was invoked")

    for name in (
        "_owned_card_ids",
        "_search_collection",
        "_search_wishlist",
        "_search_grading",
        "_search_notes",
        "_search_activity",
        "_search_signals",
        "_search_opportunities",
        "_search_reports",
        "record_search_history",
    ):
        monkeypatch.setattr(search_service, name, forbidden)

    result = search_health_probe(db_session)

    assert result.ok is True
    assert set(result.providers_skipped) == {
        "collection",
        "wishlist",
        "grading",
        "notes",
        "activity",
        "signals",
        "opportunities",
        "reports",
    }


def test_search_health_probe_executes_only_selects(db_session):
    statements: list[str] = []

    def capture_statement(
        _conn, _cursor, statement, _parameters, _context, _executemany
    ):
        statements.append(statement.lstrip().upper())

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        result = search_health_probe(db_session)
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert result.ok is True
    assert statements
    assert all(statement.startswith("SELECT") for statement in statements)
    assert not db_session.new
    assert not db_session.dirty
    assert not db_session.deleted


def test_normal_search_still_requires_keyword_only_user_id(db_session):
    parameter = inspect.signature(search).parameters["user_id"]
    assert parameter.default is inspect.Parameter.empty
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY

    with pytest.raises(TypeError, match="user_id"):
        search(db_session, "anything")

    assert "user_id" not in inspect.signature(search_health_probe).parameters


def test_public_search_endpoint_still_requires_authenticated_user(db_session):
    response = TestClient(app).get("/search", params={"q": "anything"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Bearer token required"
