from datetime import datetime, timezone

from app.models import (
    Card,
    CollectionItem,
    DashboardPreference,
    MarketWorkflowRun,
    PriceObservation,
    Source,
    WishlistItem,
)
from app.services.dashboard import DEFAULT_PREFERENCES
from app.services.market_report import generate_market_report


def make_card(db_session, **overrides) -> Card:
    fields = dict(
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        name_jp="モンキー・D・ルフィ",
        set_code="OP01",
        rarity="L",
        variant="leader",
        language="en",
    )
    fields.update(overrides)
    card = Card(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_source(db_session, name: str) -> Source:
    source = Source(name=name, base_url=f"https://{name}.example.com")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def add_observation(db_session, card, source, *, price_type, price_jpy, **kwargs):
    obs = PriceObservation(
        card_id=card.id,
        source_id=source.id,
        price_type=price_type,
        price_jpy=price_jpy,
        observed_at=kwargs.pop("observed_at", None) or datetime.now(timezone.utc),
        **kwargs,
    )
    db_session.add(obs)
    db_session.commit()
    return obs


def make_workflow_run(db_session, **overrides) -> MarketWorkflowRun:
    fields = dict(
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        status="success",
        source="yuyutei",
        limit=10,
        send_telegram=False,
        signal_events_created=0,
        signal_events_updated=0,
        signal_events_resolved=0,
        warnings_json=[],
    )
    fields.update(overrides)
    run = MarketWorkflowRun(**fields)
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


# --- preferences ------------------------------------------------------------


def test_default_preferences_created_on_first_get(client, db_session):
    assert db_session.query(DashboardPreference).count() == 0

    response = client.get("/dashboard/preferences")

    assert response.status_code == 200
    body = response.json()
    assert body["layout"] == DEFAULT_PREFERENCES["layout"]
    assert body["hidden_widgets"] == []
    assert body["pinned_cards"] == []
    assert body["default_timeframe"] == "30d"
    assert body["show_raw_market_value"] is True
    assert body["show_graded_adjusted_value"] is True
    assert body["show_wishlist_budget"] is True
    assert body["show_grading_costs"] is True

    db_session.expire_all()
    assert db_session.query(DashboardPreference).count() == 1


def test_get_preferences_returns_existing_row_unchanged(client, db_session):
    first = client.get("/dashboard/preferences").json()
    second = client.get("/dashboard/preferences").json()
    assert first == second
    assert db_session.query(DashboardPreference).count() == 1


def test_patch_preferences_updates_fields(client, db_session):
    response = client.patch(
        "/dashboard/preferences",
        json={
            "layout": ["portfolio_summary", "wishlist_targets"],
            "hidden_widgets": ["data_freshness"],
            "default_timeframe": "7d",
            "show_grading_costs": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["layout"] == ["portfolio_summary", "wishlist_targets"]
    assert body["hidden_widgets"] == ["data_freshness"]
    assert body["default_timeframe"] == "7d"
    assert body["show_grading_costs"] is False
    # Untouched fields keep their previous values (partial update).
    assert body["show_raw_market_value"] is True


def test_patch_preferences_pinned_cards_valid(client, db_session):
    card = make_card(db_session)

    response = client.patch("/dashboard/preferences", json={"pinned_cards": [card.id]})

    assert response.status_code == 200
    assert response.json()["pinned_cards"] == [card.id]


def test_patch_preferences_invalid_widget_in_layout_rejected(client, db_session):
    response = client.patch("/dashboard/preferences", json={"layout": ["not_a_widget"]})
    assert response.status_code == 400
    assert "not_a_widget" in response.json()["detail"]


def test_patch_preferences_invalid_widget_in_hidden_widgets_rejected(client, db_session):
    response = client.patch("/dashboard/preferences", json={"hidden_widgets": ["bogus_widget"]})
    assert response.status_code == 400


def test_patch_preferences_invalid_timeframe_rejected(client, db_session):
    response = client.patch("/dashboard/preferences", json={"default_timeframe": "1y"})
    assert response.status_code == 422


def test_patch_preferences_invalid_pinned_card_rejected(client, db_session):
    response = client.patch("/dashboard/preferences", json={"pinned_cards": [999999]})
    assert response.status_code == 400
    assert "999999" in response.json()["detail"]


def test_patch_preferences_non_boolean_rejected(client, db_session):
    # "yes"/"no"/"1"/"0" etc. are valid Pydantic v2 lax-mode boolean strings -
    # use a value that isn't coercible at all to prove the field is enforced.
    response = client.patch("/dashboard/preferences", json={"show_grading_costs": "banana"})
    assert response.status_code == 422


# --- overview -----------------------------------------------------------


def test_overview_works_with_empty_data(client, db_session):
    response = client.get("/dashboard/overview")

    assert response.status_code == 200
    body = response.json()
    widgets = body["widgets"]

    assert widgets["portfolio_summary"]["total_cost_basis_jpy"] == 0
    assert widgets["portfolio_chart"]["points"] == []
    assert widgets["wishlist_targets"]["items"] == []
    assert widgets["wishlist_targets"]["total_target_hit"] == 0
    assert widgets["wishlist_targets"]["total_target_budget_jpy"] == 0
    assert widgets["wishlist_targets"]["total_max_budget_jpy"] == 0
    assert widgets["top_opportunities"]["opportunities"] == []
    assert widgets["grading_status"]["total_submissions"] == 0
    assert widgets["market_report"]["report_id"] is None
    assert widgets["market_report"]["deterministic_summary_lines"] == []
    assert widgets["collection_quality"]["missing_purchase_price_count"] == 0
    assert widgets["recent_signal_events"]["events"] == []
    assert widgets["data_freshness"]["latest_refresh_at"] is None
    assert widgets["backup_status"]["tracked"] is False
    assert widgets["backup_status"]["message"] == "No backup status tracked yet"
    assert widgets["workflow_status"]["run_id"] is None
    assert widgets["recent_activity"]["events"] == []


def test_overview_includes_preferences(client, db_session):
    client.patch("/dashboard/preferences", json={"default_timeframe": "90d"})

    response = client.get("/dashboard/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["preferences"]["default_timeframe"] == "90d"
    assert body["widgets"]["portfolio_chart"]["timeframe"] == "90d"


def test_overview_includes_portfolio_summary(client, db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=2000)
    db_session.add(CollectionItem(user_id=1, card_id=card.id, quantity=1, purchase_price_jpy=1000))
    db_session.commit()

    response = client.get("/dashboard/overview")

    assert response.status_code == 200
    summary = response.json()["widgets"]["portfolio_summary"]
    assert summary["total_cost_basis_jpy"] == 1000
    assert summary["market_floor_value_jpy"] == 2000
    assert summary["pnl_vs_market_floor_jpy"] == 1000


def test_overview_includes_wishlist_targets(client, db_session):
    hit_card = make_card(db_session, card_code="OP01-001")
    miss_card = make_card(db_session, card_code="OP01-002")
    low_priority_card = make_card(db_session, card_code="OP01-003")
    snkrdunk = make_source(db_session, "snkrdunk")
    add_observation(db_session, hit_card, snkrdunk, price_type="floor", price_jpy=500)
    add_observation(db_session, miss_card, snkrdunk, price_type="floor", price_jpy=5000)
    add_observation(db_session, low_priority_card, snkrdunk, price_type="floor", price_jpy=500)

    db_session.add_all(
        [
            WishlistItem(user_id=1, card_id=hit_card.id, priority="grail", target_buy_price_jpy=1000),
            WishlistItem(user_id=1, card_id=miss_card.id, priority="grail", target_buy_price_jpy=1000),
            WishlistItem(user_id=1, card_id=low_priority_card.id, priority="low", target_buy_price_jpy=1000),
        ]
    )
    db_session.commit()

    response = client.get("/dashboard/overview")

    assert response.status_code == 200
    widget = response.json()["widgets"]["wishlist_targets"]
    assert widget["total_target_hit"] == 1
    assert len(widget["items"]) == 1
    assert widget["items"][0]["card_code"] == "OP01-001"


def test_overview_includes_top_opportunities(client, db_session):
    from app.models import MarketSignalEvent

    card = make_card(db_session)
    now = datetime.now(timezone.utc)
    db_session.add(
        MarketSignalEvent(
            signal_type="snkrdunk_floor_below_yuyutei_sell",
            dedupe_key="dedupe-dashboard-1",
            severity="info",
            suggested_action="review_buy_opportunity",
            status="open",
            message="test",
            card_id=card.id,
            first_seen_at=now,
            last_seen_at=now,
            seen_count=1,
        )
    )
    db_session.commit()

    response = client.get("/dashboard/overview")

    assert response.status_code == 200
    opportunities = response.json()["widgets"]["top_opportunities"]["opportunities"]
    assert len(opportunities) == 1
    assert opportunities[0]["card_id"] == card.id


def test_overview_includes_grading_status(client, db_session):
    card = make_card(db_session)
    item = CollectionItem(user_id=1, card_id=card.id, quantity=1)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    response = client.post(
        "/grading/submissions",
        json={
            "collection_item_id": item.id,
            "grading_company": "PSA",
            "submission_status": "grading",
            "grading_fee_jpy": 3000,
        },
    )
    assert response.status_code == 201

    overview = client.get("/dashboard/overview").json()
    grading_widget = overview["widgets"]["grading_status"]
    assert grading_widget["total_submissions"] == 1
    assert grading_widget["submitted_or_grading_count"] == 1
    assert grading_widget["received_count"] == 0
    assert grading_widget["total_grading_cost_jpy"] == 3000


def test_overview_includes_latest_market_report(client, db_session):
    report = generate_market_report(db_session)

    response = client.get("/dashboard/overview")

    assert response.status_code == 200
    widget = response.json()["widgets"]["market_report"]
    assert widget["report_id"] == report.id
    assert widget["total_opportunities"] == report.total_opportunities
    assert len(widget["deterministic_summary_lines"]) <= 3


def test_overview_includes_workflow_status(client, db_session):
    run = make_workflow_run(db_session, status="partial_success", telegram_digest_status="sent")

    response = client.get("/dashboard/overview")

    assert response.status_code == 200
    widget = response.json()["widgets"]["workflow_status"]
    assert widget["run_id"] == run.id
    assert widget["status"] == "partial_success"
    assert widget["telegram_digest_status"] == "sent"


def test_overview_requires_login(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    unauth_client = TestClient(app)
    response = unauth_client.get("/dashboard/overview")
    assert response.status_code == 401
