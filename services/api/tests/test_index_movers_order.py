"""Both rankings select from the complete archived mover population."""

import pytest

from app.services.card_pirate_index import compute_step
from app.services.card_pirate_index_movers import MAX_MOVERS, get_index_movers
from app.services.card_pirate_index_replay import load_snapshot_days
from test_analytics_card_pirate_index_movers import (
    D6, D7, archive, point, seed_print, snap,  # noqa: F401
)


@pytest.fixture
def different_leaders(db_session):
    total = MAX_MOVERS + 5
    for pid in range(1, total + 1):
        seed_print(db_session, pid, code=f"OP17-{pid:03d}")
        snap(db_session, pid, D6, 10000)
        # +24.xx% dominates move order, but -21% has a greater absolute
        # capped log return. The top impact is outside the first 20 moves.
        snap(db_session, pid, D7, 7900 if pid == total else 12400 + pid)
    point(db_session, D6, prior=None, constituents=0, eligible=total,
          value="1000.0000", base=True)
    db_session.commit()
    days = {d.point_date: d for d in load_snapshot_days(db_session, history_start=D6, end=D7)}
    step = compute_step(days[D6], days[D7])
    point(db_session, D7, prior=D6, constituents=step.constituent_count,
          eligible=total, value="1000.5", chain=step.step_log_return,
          up=step.movers_up, down=step.movers_down, flat=step.movers_flat,
          capped=step.capped_count)
    db_session.commit()
    return total


def test_order_selects_before_truncation_with_full_ranks(client, db_session, different_leaders, monkeypatch):
    monkeypatch.setattr("app.services.cache_headers.is_development_environment", lambda: True)
    total = different_leaders
    default = client.get("/analytics/index/movers")
    move = client.get("/analytics/index/movers?order=move")
    impact = client.get("/analytics/index/movers?order=impact")
    assert default.status_code == move.status_code == impact.status_code == 200
    assert default.content == move.content
    by_move, by_impact = move.json(), impact.json()
    assert by_move["order"] == "move"
    assert by_impact["order"] == "impact"
    assert by_move["movers"][0]["card_print_id"] == total - 1
    assert by_impact["movers"][0]["card_print_id"] == total
    assert total not in {m["card_print_id"] for m in by_move["movers"]}
    assert by_impact["movers"][0]["move_rank"] == total
    assert by_impact["movers"][0]["impact_rank"] == 1

    full = get_index_movers(db_session, limit=total)
    full_by_id = {m.card_print_id: m for m in full.movers}
    for body, ranking in [(by_move, "move_rank"), (by_impact, "impact_rank")]:
        assert body["truncated"] is True
        assert len(body["movers"]) == MAX_MOVERS
        assert body["movers_count"] == body["constituent_count"] == total
        assert body["unchanged_count"] == 0
        assert [m[ranking] for m in body["movers"]] == list(range(1, MAX_MOVERS + 1))
        for mover in body["movers"]:
            complete = full_by_id[mover["card_print_id"]]
            assert mover["move_rank"] == complete.move_rank
            assert mover["impact_rank"] == complete.impact_rank
            assert mover["contribution_log_return"] == str(complete.contribution_log_return)
    for field in by_move.keys() - {"movers", "order"}:
        assert by_move[field] == by_impact[field]
    # Reordering must not change any payload field on overlapping movers.
    overlap = {m["card_print_id"]: m for m in by_move["movers"]}
    for mover in by_impact["movers"]:
        if mover["card_print_id"] in overlap:
            assert mover == overlap[mover["card_print_id"]]
    assert move.headers["X-Cache-Key"].endswith(":move")
    assert impact.headers["X-Cache-Key"].endswith(":impact")


@pytest.mark.parametrize("date", ["2026-09-05", "2026-09-06"])
def test_base_and_quiet_day_keep_existing_fields(client, archive, date):
    default = client.get("/analytics/index/movers", params={"date": date}).json()
    impact = client.get("/analytics/index/movers", params={"date": date, "order": "impact"}).json()
    assert default.pop("order") == "move"
    assert impact.pop("order") == "impact"
    assert default == impact
    assert impact["movers"] == []
    assert impact["truncated"] is False


@pytest.mark.parametrize("order", ["unknown", "MOVE", "", "gain"])
def test_unknown_order_is_400_even_without_an_archive(client, db_session, order):
    response = client.get("/analytics/index/movers", params={"order": order})
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid order. Must be one of: move, impact"


def test_openapi_exposes_order_enum_and_default(client):
    schema = client.get("/openapi.json").json()
    parameters = schema["paths"]["/analytics/index/movers"]["get"]["parameters"]
    order = next(p["schema"] for p in parameters if p["name"] == "order")
    assert order["enum"] == ["move", "impact"]
    assert order["default"] == "move"
    assert schema["components"]["schemas"]["CardPirateIndexMoversOut"]["properties"]["order"]["enum"] == ["move", "impact"]
