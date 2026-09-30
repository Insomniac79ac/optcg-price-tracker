from app.services.freshness_capacity import CapacityAssumptions, simulate_capacity


def test_capacity_deficit_is_reported_without_relaxing_deadlines():
    overloaded = simulate_capacity(
        CapacityAssumptions(name="overloaded", seconds_per_capture=20, days=3)
    )
    assert not overloaded["capacity_can_sustain_check_cadence"]
    assert not overloaded["simulated_deadlines_met"]
    assert overloaded["daily"][-1]["expired_current_prices"] > 0
    assert overloaded["daily"][0]["backlog_growth_since_previous_day"] > 0
    assert overloaded["offered_load_deficit_captures_per_day"] > 0
    assert overloaded["assumptions"]["execution_headroom_seconds"] == 3600


def test_sufficient_serial_capacity_and_shared_grade_capture():
    result = simulate_capacity(CapacityAssumptions(name="sufficient"))
    assert result["capacity_can_sustain_check_cadence"]
    assert result["simulated_deadlines_met"]
    assert result["serial_workers"] == 1
    assert result["price_categories_share_product_capture"]
    assert result["processing_chunks_started"] > 7  # no once-a-day 70-product cap
