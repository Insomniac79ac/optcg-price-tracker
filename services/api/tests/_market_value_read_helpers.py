"""Mock persisted rows, independent of HTTP and source/archive loading."""

import json
from datetime import date, timedelta
from decimal import Decimal, localcontext
from pathlib import Path

from app.models.market_value_point import MarketValuePoint
from app.models.release_product import ReleaseProduct

END = date(2026, 9, 26)


def release(
    db, release_id=174, code="OP-05", released_on=date(2023, 8, 26), **overrides
):
    values = dict(
        id=release_id,
        official_code=code,
        display_name=f"Authoritative {code or 'special'}",
        first_seen_name="Original official name",
        source_catalogue="bandai_jp",
        source_series_id=str(release_id),
        source_url="https://example.test/product",
        verification_status="verified",
        released_on=released_on,
        release_date_source="DATE_VERIFIED_SINGLE_SOURCE" if released_on else None,
    )
    values.update(overrides)
    row = ReleaseProduct(**values)
    db.add(row)
    db.flush()
    return row


def points(
    *,
    release_id=None,
    count=8,
    end=END,
    value=30000,
    priced=300,
    physical=300,
    breaks=None,
    last_pair=None,
    methodology_version=1,
):
    """Coherent stored aggregate evidence, with explicit mock publication flags.

    This factory does not claim to reconstruct the staging archive. The frozen
    census test below uses audited endpoint counts/sums plus synthetic daily
    chain evidence; the staging read-only check independently verifies reality.
    """
    breaks = breaks or {}
    start = end - timedelta(days=count - 1)
    rows = []
    segment = 0
    numerator = denominator = 1
    for offset in range(count):
        day = start + timedelta(days=offset)
        prior = rows[-1] if rows else None
        eligible = None if prior is None else day not in breaks
        reason = None if prior is None else breaks.get(day, "publishable")
        p, q = last_pair if day == end and last_pair else (value or 0, value or 0)
        with localcontext() as context:
            context.prec = 50
            ratio = Decimal(q) / Decimal(p) if p else None
            if eligible:
                numerator *= q
                denominator *= p
            elif prior is not None:
                segment += 1
                numerator = denominator = 1
            factor = Decimal(numerator) / Decimal(denominator)
        rows.append(
            MarketValuePoint(
                scope_kind="overall" if release_id is None else "release",
                release_product_id=release_id,
                methodology_version=methodology_version,
                point_date=day,
                tracked_value_jpy=value or None,
                priced_print_count=priced,
                total_physical_print_count=physical,
                prior_point_date=prior.point_date if prior else None,
                step_days=1 if prior else None,
                prior_tracked_value_jpy=prior.tracked_value_jpy if prior else None,
                prior_priced_print_count=priced if prior else None,
                prior_total_physical_print_count=physical if prior else None,
                comparable_print_count=priced if prior else None,
                prior_comparable_value_jpy=p if prior else None,
                current_comparable_value_jpy=q if prior else None,
                step_ratio=ratio if prior else None,
                segment_number=segment,
                performance_factor=factor,
                step_publication_eligible=eligible,
                publication_reasons=reason,
                membership_revision="mock-frozen-census",
                prior_version_pairs="3:2" if prior else None,
                current_version_pairs="3:2",
            )
        )
    return rows


def seed(db, **kwargs):
    rows = points(**kwargs)
    db.add_all(rows)
    db.commit()
    return rows


def frozen_census(db):
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures" / "market_value_a1_release_coverage.json"
        ).read_text()
    )
    start = END - timedelta(days=36)
    transition = date(2026, 9, 3)
    overall = points(
        count=37,
        value=262279,
        priced=639,
        physical=4316,
        breaks={transition: "index_version_changed"},
        # Synthetic comparable sums yield -3.943982% to six decimal places.
        last_pair=(228855, 219829),
    )
    db.add_all(overall)
    qualifiers = {
        "EB-01",
        "EB-02",
        "EB-03",
        "EB-04",
        "OP-01",
        "OP-02",
        "OP-03",
        "OP-04",
        "OP-13",
    }
    for item in fixture["releases"]:
        release(db, item["id"], item["code"])
        if item["code"] in qualifiers:
            breaks = {transition: "index_version_changed"}
        else:
            reason = (
                "insufficient_comparable_prints"
                if item["priced"]
                else "non_positive_comparable_value"
            )
            breaks = {start + timedelta(days=n): reason for n in range(1, 37)}
        db.add_all(
            points(
                release_id=item["id"],
                count=37,
                value=item["value_jpy"],
                priced=item["priced"],
                physical=item["physical"],
                breaks=breaks,
            )
        )
    db.commit()
