from fastapi.testclient import TestClient

from app.main import app
from app.models import SavedView
from app.seed_saved_views import PRESETS, seed_saved_views


def create_view(client, **overrides):
    body = dict(
        name="Review Buy",
        route_path="/analytics/buy-decisions",
        view_type="buy_decisions",
        scope="analytics",
        filters_json={"action": "review_buy", "min_score": 70},
    )
    body.update(overrides)
    return client.post("/saved-views", json=body)


def test_create_saved_view(client, db_session):
    response = create_view(client)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["name"] == "Review Buy"
    assert data["scope"] == "analytics"
    assert data["density"] == "compact"
    assert data["is_default"] is False
    assert data["pinned"] is False
    assert data["usage_count"] == 0
    assert data["last_used_at"] is None
    assert data["filters_json"] == {"action": "review_buy", "min_score": 70}


def test_create_saved_view_blank_name_rejected(client, db_session):
    response = create_view(client, name="   ")
    assert response.status_code == 422


def test_create_saved_view_invalid_scope_rejected(client, db_session):
    response = create_view(client, scope="not-a-real-scope")
    assert response.status_code == 422


def test_create_saved_view_non_object_filters_rejected(client, db_session):
    response = create_view(client, filters_json=["not", "an", "object"])
    assert response.status_code == 422


def test_create_saved_view_forbidden_key_rejected(client, db_session):
    response = create_view(client, filters_json={"admin_token": "secret-value"})
    assert response.status_code == 400


def test_create_saved_view_confirm_text_key_rejected(client, db_session):
    response = create_view(client, filters_json={"confirm_text": "MERGE"})
    assert response.status_code == 400


def test_get_saved_view(client, db_session):
    created = create_view(client).json()
    response = client.get(f"/saved-views/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_saved_view_not_found(client, db_session):
    response = client.get("/saved-views/999999")
    assert response.status_code == 404


def test_list_saved_views_by_route_path(client, db_session):
    create_view(client, name="Review Buy")
    create_view(
        client,
        name="Critical Mapping Issues",
        route_path="/admin/source-mapping-quality",
        view_type="source_mapping_quality",
        scope="admin",
        filters_json={"risk_level": "critical"},
    )

    response = client.get("/saved-views", params={"route_path": "/analytics/buy-decisions"})
    assert response.status_code == 200
    data = response.json()
    assert data["pagination"]["total"] == 1
    assert data["items"][0]["name"] == "Review Buy"


def test_list_saved_views_by_scope(client, db_session):
    create_view(client, name="Review Buy")
    create_view(
        client,
        name="Critical Mapping Issues",
        route_path="/admin/source-mapping-quality",
        view_type="source_mapping_quality",
        scope="admin",
        filters_json={"risk_level": "critical"},
    )

    response = client.get("/saved-views", params={"scope": "admin"})
    assert response.status_code == 200
    data = response.json()
    assert data["pagination"]["total"] == 1
    assert data["items"][0]["name"] == "Critical Mapping Issues"


def test_update_saved_view(client, db_session):
    created = create_view(client).json()
    response = client.patch(
        f"/saved-views/{created['id']}",
        json={"description": "Updated description", "pinned": True},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["description"] == "Updated description"
    assert data["pinned"] is True


def test_update_saved_view_not_found(client, db_session):
    response = client.patch("/saved-views/999999", json={"pinned": True})
    assert response.status_code == 404


def test_update_saved_view_invalid_density_rejected(client, db_session):
    created = create_view(client).json()
    response = client.patch(f"/saved-views/{created['id']}", json={"density": "ultra-dense"})
    assert response.status_code == 422


def test_delete_saved_view(client, db_session):
    created = create_view(client).json()
    response = client.delete(f"/saved-views/{created['id']}")
    assert response.status_code == 204

    list_response = client.get("/saved-views")
    assert list_response.json()["pagination"]["total"] == 0


def test_delete_saved_view_not_found(client, db_session):
    response = client.delete("/saved-views/999999")
    assert response.status_code == 404


def test_use_saved_view_increments_usage_and_sets_last_used(client, db_session):
    created = create_view(client).json()
    assert created["usage_count"] == 0
    assert created["last_used_at"] is None

    response = client.post(f"/saved-views/{created['id']}/use")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["usage_count"] == 1
    assert data["last_used_at"] is not None

    response2 = client.post(f"/saved-views/{created['id']}/use")
    assert response2.json()["usage_count"] == 2


def test_set_default_unsets_other_defaults_for_same_route_and_view_type(client, db_session):
    first = create_view(client, name="Review Buy").json()
    second = create_view(client, name="Wishlist Target Hits", filters_json={"action": "review_buy"}).json()
    # A saved view on a different route_path/view_type - must be unaffected.
    other = create_view(
        client,
        name="Critical Mapping Issues",
        route_path="/admin/source-mapping-quality",
        view_type="source_mapping_quality",
        scope="admin",
        filters_json={"risk_level": "critical"},
    ).json()

    client.post(f"/saved-views/{first['id']}/set-default")
    client.post(f"/saved-views/{other['id']}/set-default")

    response = client.post(f"/saved-views/{second['id']}/set-default")
    assert response.status_code == 200, response.text
    assert response.json()["is_default"] is True

    first_after = client.get(f"/saved-views/{first['id']}").json()
    assert first_after["is_default"] is False

    other_after = client.get(f"/saved-views/{other['id']}").json()
    assert other_after["is_default"] is True


def test_clear_default(client, db_session):
    created = create_view(client).json()
    client.post(f"/saved-views/{created['id']}/set-default")
    assert client.get(f"/saved-views/{created['id']}").json()["is_default"] is True

    response = client.post(
        "/saved-views/clear-default",
        json={"route_path": "/analytics/buy-decisions", "view_type": "buy_decisions"},
    )
    assert response.status_code == 204

    assert client.get(f"/saved-views/{created['id']}").json()["is_default"] is False


def test_saved_views_require_login(db_session):
    unauth_client = TestClient(app)
    response = unauth_client.get("/saved-views")
    assert response.status_code == 401


def test_saved_views_do_not_require_admin_token(client, db_session):
    """Confirms the router depends only on require_current_user, never
    require_admin_token - a bearer token with no X-Admin-Token header must
    still succeed."""
    no_admin_token_client = TestClient(app)
    no_admin_token_client.headers.update(dict(client.headers))
    del no_admin_token_client.headers["X-Admin-Token"]

    response = no_admin_token_client.get("/saved-views")
    assert response.status_code == 200


def test_seed_saved_views_is_idempotent(db_session):
    inserted_first = seed_saved_views(db_session)
    db_session.commit()
    assert inserted_first == len(PRESETS)
    assert db_session.query(SavedView).count() == len(PRESETS)

    inserted_second = seed_saved_views(db_session)
    db_session.commit()
    assert inserted_second == 0
    assert db_session.query(SavedView).count() == len(PRESETS)
