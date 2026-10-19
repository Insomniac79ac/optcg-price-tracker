"""`grade_key` vocabulary (accepted Q13; new-sources plan §2.1).

raw:<condition> is an ungraded copy; graded:<grader>:<grade>[:flawed] is a slab. NULL on a
price_observations row means "derive from price_type / condition_label", which is every Yuyu-Tei
and SNKRDUNK row. Graded keys exist in source_product_variants only: while PSA10 is OFF (decision
N10) no graded key may reach price_observations, which the database also enforces.

The SQL patterns are restated in the migration that created the CHECKs (7a52e9b48e8a), as
migrations must not import application code; tests hold the two equal.
"""

from __future__ import annotations

import re

RAW_CONDITIONS = ("A", "A-", "B", "C", "D", "damaged", "play")
GRADED_UNKNOWN = "graded:unknown"

# Grader is upper-case letters (PSA, BGS, CGC, ARS); grade is an integer or a half grade.
SQL_PATTERN = r"^(raw:(A|A-|B|C|D|damaged|play)|graded:(unknown|[A-Z]{2,8}:[0-9]{1,2}(\.5)?([:]flawed)?))$"
PATTERN = re.compile(SQL_PATTERN)


def is_valid(grade_key: str) -> bool:
    return bool(PATTERN.fullmatch(grade_key))


def is_raw(grade_key: str | None) -> bool:
    return grade_key is not None and grade_key.startswith("raw:")


def raw(condition: str) -> str:
    key = f"raw:{condition}"
    if condition not in RAW_CONDITIONS:
        raise ValueError(f"unknown raw condition {condition!r}")
    return key


def graded(grader: str | None, grade: str | None, *, flawed: bool = False) -> str:
    """graded:<grader>:<grade>[:flawed], or graded:unknown when either part does not parse."""
    if not grader or not grade:
        return GRADED_UNKNOWN
    key = f"graded:{grader.upper()}:{grade}" + (":flawed" if flawed else "")
    return key if is_valid(key) else GRADED_UNKNOWN
