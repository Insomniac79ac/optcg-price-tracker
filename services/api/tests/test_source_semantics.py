"""app.services.source_semantics - the pure per-observation semantics
classifier. Every test here is a plain function call: the module touches no
database and has no side effects, so none of these need a db_session.

Nothing in production calls the classifier yet (Task 1C-2A is the foundation
only), so these tests are the entire behavioural contract for it.
"""

from app.services.source_semantics import (
    PLATFORM_FLOOR,
    SNKRDUNK,
    SOURCE_SEMANTICS,
    SOURCE_SEMANTICS_VERSION,
    STORED_FLOOR,
    SourceSemantics,
    classify_observation,
)


def assert_unconstrained(semantics: SourceSemantics) -> None:
    assert semantics.constraint is None
    assert semantics.eligible is True
    assert semantics.ineligible_reason is None


def assert_platform_floor(semantics: SourceSemantics) -> None:
    assert semantics.constraint == "platform_floor"
    assert semantics.eligible is False
    assert semantics.ineligible_reason == "platform_floor"


# --- A: another source's normal observation is untouched ------------------


def test_yuyutei_sell_is_unconstrained():
    assert_unconstrained(classify_observation("yuyutei", "sell", 580))


def test_yuyutei_sell_at_the_snkrdunk_minimum_is_still_unconstrained():
    """The threshold is SNKRDUNK's, not a global one - a Yuyu-Tei price that
    happens to be exactly 1000 is an ordinary retail price."""
    assert_unconstrained(classify_observation("yuyutei", "sell", 1000))


def test_bandai_is_unconstrained():
    assert_unconstrained(classify_observation("bandai", "sell", 1000))


# --- B, C: SNKRDUNK floors above the configured minimum -------------------


def test_snkrdunk_floor_1500_is_unconstrained():
    """Task 1C-2A deliberately does not classify 1500 as constrained, even
    though some 1500 observations diverge sharply from Yuyu-Tei - no threshold
    beyond the verified platform minimum is inferred here."""
    assert_unconstrained(classify_observation(SNKRDUNK, STORED_FLOOR, 1500))


def test_snkrdunk_floor_just_above_minimum_is_unconstrained():
    assert_unconstrained(classify_observation(SNKRDUNK, STORED_FLOOR, 1001))


# --- D, E: at and below the configured minimum ----------------------------


def test_snkrdunk_floor_at_minimum_is_platform_floor():
    assert_platform_floor(classify_observation(SNKRDUNK, STORED_FLOOR, 1000))


def test_snkrdunk_floor_below_minimum_is_platform_floor():
    """`<=`, not `==`: a value under the stated minimum is equally
    constrained, and the rule keeps working if SNKRDUNK ever reports one."""
    assert_platform_floor(classify_observation(SNKRDUNK, STORED_FLOOR, 999))


def test_snkrdunk_floor_far_below_minimum_is_platform_floor():
    assert_platform_floor(classify_observation(SNKRDUNK, STORED_FLOOR, 1))


# --- F: SNKRDUNK, but not the configured price_type -----------------------


def test_snkrdunk_non_floor_price_type_at_the_minimum_is_unconstrained():
    """Only the stored "floor" price_type carries the platform minimum. A
    sold price of 1000 is a real transaction, not a listing constraint."""
    assert_unconstrained(classify_observation(SNKRDUNK, "sold", 1000))


def test_snkrdunk_unknown_price_type_is_unconstrained():
    assert_unconstrained(classify_observation(SNKRDUNK, "buy", 1000))


# --- The Task 1C-1 audit correction, guarded ------------------------------


def test_listing_floor_is_not_treated_as_the_stored_floor_price_type():
    """`listing_floor` is only the API-facing reference_type
    (app.services.market_index._resolve_snkrdunk); the stored price_type is
    `floor`. Classifying on the API-facing name must never work by accident -
    it would match zero real rows while appearing correct in a test."""
    assert_unconstrained(classify_observation(SNKRDUNK, "listing_floor", 1000))
    assert_unconstrained(classify_observation(SNKRDUNK, "listing_floor", 999))


def test_stored_floor_constant_is_the_stored_name():
    assert STORED_FLOOR == "floor"
    assert STORED_FLOOR != "listing_floor"


# --- G: unknown / future sources ------------------------------------------


def test_unknown_future_source_is_unconstrained():
    """A source with no configured semantics must be treated exactly as it is
    treated today, never rejected for being unlisted."""
    assert_unconstrained(classify_observation("cardrush", "floor", 1000))


def test_unknown_source_does_not_raise_for_any_price_type():
    for price_type in ("floor", "sell", "buy", "sold", "", "totally-made-up"):
        assert_unconstrained(classify_observation("cardmarket", price_type, 1000))


def test_empty_source_name_is_unconstrained():
    assert_unconstrained(classify_observation("", "floor", 1000))


# --- H: missing value -----------------------------------------------------


def test_none_value_is_safe_for_a_configured_source():
    """Deliberately not this module's concern: Market Index already gates on
    `value_jpy is not None` in _compute_index_fields."""
    assert_unconstrained(classify_observation(SNKRDUNK, STORED_FLOOR, None))


def test_none_value_is_safe_for_an_unknown_source():
    assert_unconstrained(classify_observation("cardrush", "sell", None))


# --- Result shape and config ----------------------------------------------


def test_default_semantics_are_unconstrained_and_eligible():
    assert_unconstrained(SourceSemantics())


def test_result_is_immutable():
    """Frozen so the shared default instance can never be mutated by a
    caller into a state other callers would then observe."""
    semantics = classify_observation(SNKRDUNK, STORED_FLOOR, 1000)
    try:
        semantics.eligible = True  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("SourceSemantics should be frozen")


def test_repeated_calls_do_not_share_mutable_state():
    first = classify_observation(SNKRDUNK, STORED_FLOOR, 1000)
    second = classify_observation("yuyutei", "sell", 580)
    assert_platform_floor(first)
    assert_unconstrained(second)


def test_platform_minimum_lives_only_in_central_config():
    """The literal threshold must be reachable from the config, so no other
    module ever needs to restate it."""
    rule = SOURCE_SEMANTICS[SNKRDUNK][STORED_FLOOR]
    assert rule.platform_minimum_jpy == 1000
    assert rule.at_or_below_minimum == PLATFORM_FLOOR


def test_snkrdunk_configures_only_the_stored_floor_price_type():
    assert set(SOURCE_SEMANTICS[SNKRDUNK]) == {STORED_FLOOR}


# --- Version --------------------------------------------------------------


def test_source_semantics_version_is_1():
    assert SOURCE_SEMANTICS_VERSION == 1
