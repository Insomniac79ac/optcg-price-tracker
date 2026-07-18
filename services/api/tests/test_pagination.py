import pytest
from fastapi import HTTPException

from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, pagination_response, parse_pagination


# --- pagination_response ---------------------------------------------------


def test_pagination_response_has_next_true_when_more_rows_remain():
    meta = pagination_response(items=[1, 2, 3], total=10, limit=3, offset=0)
    assert meta.has_next is True
    assert meta.next_offset == 3


def test_pagination_response_has_next_false_on_last_full_page():
    meta = pagination_response(items=[1, 2, 3], total=6, limit=3, offset=3)
    assert meta.has_next is False
    assert meta.next_offset is None


def test_pagination_response_has_next_false_on_short_final_page():
    # A short final page (returned items < limit) still correctly reports
    # no next page even though offset + limit would exceed total.
    meta = pagination_response(items=[1, 2], total=5, limit=3, offset=3)
    assert meta.has_next is False
    assert meta.next_offset is None


def test_pagination_response_has_previous_true_when_offset_positive():
    meta = pagination_response(items=[1], total=10, limit=5, offset=5)
    assert meta.has_previous is True
    assert meta.previous_offset == 0


def test_pagination_response_has_previous_false_at_offset_zero():
    meta = pagination_response(items=[1, 2, 3], total=10, limit=3, offset=0)
    assert meta.has_previous is False
    assert meta.previous_offset is None


def test_pagination_response_previous_offset_clamped_to_zero():
    # offset=2, limit=5 -> naive offset-limit would be negative.
    meta = pagination_response(items=[1, 2], total=7, limit=5, offset=2)
    assert meta.has_previous is True
    assert meta.previous_offset == 0


def test_pagination_response_middle_page_has_both_next_and_previous():
    meta = pagination_response(items=[1, 2, 3], total=10, limit=3, offset=3)
    assert meta.has_next is True
    assert meta.has_previous is True
    assert meta.next_offset == 6
    assert meta.previous_offset == 0


def test_pagination_response_empty_total():
    meta = pagination_response(items=[], total=0, limit=100, offset=0)
    assert meta.has_next is False
    assert meta.has_previous is False
    assert meta.next_offset is None
    assert meta.previous_offset is None
    assert meta.total == 0


def test_pagination_response_echoes_limit_offset_total():
    meta = pagination_response(items=[1, 2], total=42, limit=2, offset=10)
    assert meta.limit == 2
    assert meta.offset == 10
    assert meta.total == 42


# --- parse_pagination --------------------------------------------------------


def test_parse_pagination_defaults_when_none():
    limit, offset = parse_pagination(None, None)
    assert limit == DEFAULT_LIMIT
    assert offset == 0


def test_parse_pagination_passes_through_valid_values():
    limit, offset = parse_pagination(50, 20)
    assert limit == 50
    assert offset == 20


def test_parse_pagination_rejects_negative_offset():
    with pytest.raises(HTTPException) as exc_info:
        parse_pagination(10, -1)
    assert exc_info.value.status_code == 422


def test_parse_pagination_rejects_zero_limit():
    with pytest.raises(HTTPException) as exc_info:
        parse_pagination(0, 0)
    assert exc_info.value.status_code == 422


def test_parse_pagination_rejects_negative_limit():
    with pytest.raises(HTTPException) as exc_info:
        parse_pagination(-5, 0)
    assert exc_info.value.status_code == 422


def test_parse_pagination_rejects_limit_over_max():
    with pytest.raises(HTTPException) as exc_info:
        parse_pagination(MAX_LIMIT + 1, 0)
    assert exc_info.value.status_code == 422


def test_parse_pagination_allows_limit_at_max():
    limit, offset = parse_pagination(MAX_LIMIT, 0)
    assert limit == MAX_LIMIT


def test_parse_pagination_allows_offset_zero():
    limit, offset = parse_pagination(10, 0)
    assert offset == 0


def test_parse_pagination_custom_default_and_max_limit():
    # admin_db_backups.py-style override: smaller default/max than the
    # global DEFAULT_LIMIT/MAX_LIMIT.
    limit, offset = parse_pagination(None, None, default_limit=10, max_limit=50)
    assert limit == 10
    assert offset == 0

    with pytest.raises(HTTPException) as exc_info:
        parse_pagination(51, 0, default_limit=10, max_limit=50)
    assert exc_info.value.status_code == 422

    limit, offset = parse_pagination(50, 0, default_limit=10, max_limit=50)
    assert limit == 50
