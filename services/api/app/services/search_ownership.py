"""Fail-closed ownership guard for personal reads (saved views)."""


def require_user_id(user_id: int) -> int:
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("A trusted current user ID is required")
    return user_id
