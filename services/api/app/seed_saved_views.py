"""Seed a fixed set of useful saved-view presets (see docs/operations.md,
"Saved views workflow"). Idempotent by (route_path, view_type, name) -
matching the table's uq_saved_views_route_type_name unique constraint -
safe to run repeatedly (e.g. on every deploy)."""

import argparse

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import SavedView

PRESETS: list[dict] = [
    {
        "route_path": "/analytics/buy-decisions",
        "view_type": "buy_decisions",
        "scope": "analytics",
        "name": "Review Buy",
        "description": "Cards flagged review_buy with at least a moderate score.",
        "filters_json": {"action": "review_buy", "min_score": 70},
    },
    {
        "route_path": "/analytics/buy-decisions",
        "view_type": "buy_decisions",
        "scope": "analytics",
        "name": "Wishlist Target Hits",
        "description": "All review_buy candidates, regardless of score.",
        "filters_json": {"action": "review_buy"},
    },
    {
        "route_path": "/analytics/buy-decisions",
        "view_type": "buy_decisions",
        "scope": "analytics",
        "name": "Missing Buy Data",
        "description": "Candidates that can't be scored yet due to missing data.",
        "filters_json": {"action": "missing_data"},
    },
    {
        "route_path": "/analytics/sell-decisions",
        "view_type": "sell_decisions",
        "scope": "analytics",
        "name": "Review Sell",
        "description": "Cards flagged review_sell with at least a moderate score.",
        "filters_json": {"action": "review_sell", "min_score": 70},
    },
    {
        "route_path": "/analytics/sell-decisions",
        "view_type": "sell_decisions",
        "scope": "analytics",
        "name": "Grade First",
        "description": "Cards where grading before selling looks favorable.",
        "filters_json": {"action": "grade_first"},
    },
    {
        "route_path": "/analytics/sell-decisions",
        "view_type": "sell_decisions",
        "scope": "analytics",
        "name": "Missing Sell Data",
        "description": "Candidates that can't be scored yet due to missing data.",
        "filters_json": {"action": "missing_data"},
    },
    {
        "route_path": "/analytics/portfolio-risk",
        "view_type": "portfolio_risk",
        "scope": "analytics",
        "name": "High Risk Review",
        "description": "Portfolio risk under the raw market valuation mode.",
        "filters_json": {"valuation_mode": "raw_market"},
    },
    {
        "route_path": "/analytics/portfolio-risk",
        "view_type": "portfolio_risk",
        "scope": "analytics",
        "name": "Graded Adjusted Risk",
        "description": "Portfolio risk under the graded-adjusted valuation mode.",
        "filters_json": {"valuation_mode": "graded_adjusted"},
    },
    {
        "route_path": "/admin/source-mapping-quality",
        "view_type": "source_mapping_quality",
        "scope": "admin",
        "name": "Critical Mapping Issues",
        "description": "Source mappings at critical risk.",
        "filters_json": {"risk_level": "critical"},
    },
    {
        "route_path": "/admin/source-mapping-quality",
        "view_type": "source_mapping_quality",
        "scope": "admin",
        "name": "Low Confidence Mappings",
        "description": "Source mappings with low match confidence.",
        "filters_json": {"confidence_label": "low"},
    },
    {
        "route_path": "/admin/source-mapping-quality",
        "view_type": "source_mapping_quality",
        "scope": "admin",
        "name": "Duplicate Source URLs",
        "description": "Mappings sharing a source URL with another mapping.",
        "filters_json": {"issue_type": "duplicate_source_url"},
    },
    {
        "route_path": "/admin/catalog-coverage",
        "view_type": "catalog_coverage",
        "scope": "admin",
        "name": "Metadata Gaps",
        "description": "Cards missing catalog metadata.",
        "filters_json": {"gap_type": "metadata"},
    },
    {
        "route_path": "/admin/catalog-coverage",
        "view_type": "catalog_coverage",
        "scope": "admin",
        "name": "Mapping Gaps",
        "description": "Cards missing a source mapping.",
        "filters_json": {"gap_type": "mapping"},
    },
    {
        "route_path": "/admin/catalog-coverage",
        "view_type": "catalog_coverage",
        "scope": "admin",
        "name": "Price Gaps",
        "description": "Cards missing recent price coverage.",
        "filters_json": {"gap_type": "price"},
    },
    {
        "route_path": "/admin/price-source-health",
        "view_type": "price_source_health",
        "scope": "admin",
        "name": "Stale Prices",
        "description": "Mappings with a stale latest price.",
        "filters_json": {"gap_type": "stale"},
    },
    {
        "route_path": "/admin/price-source-health",
        "view_type": "price_source_health",
        "scope": "admin",
        "name": "Missing Prices",
        "description": "Mappings with no recent price observation.",
        "filters_json": {"gap_type": "missing"},
    },
    {
        "route_path": "/admin/price-source-health",
        "view_type": "price_source_health",
        "scope": "admin",
        "name": "Blocked Sources",
        "description": "Sources currently blocked from automated discovery.",
        "filters_json": {"gap_type": "blocked"},
    },
    {
        "route_path": "/admin/import-validation",
        "view_type": "import_validation",
        "scope": "admin",
        "name": "Failed Validations",
        "description": "Import validation reports that failed.",
        "filters_json": {"valid": False},
    },
]


def seed_saved_views(db: Session) -> int:
    """Idempotent by (route_path, view_type, name). Returns the number of
    rows actually inserted (0 on a re-run against an already-seeded DB)."""
    inserted = 0
    for preset in PRESETS:
        exists = (
            db.query(SavedView)
            .filter_by(
                route_path=preset["route_path"],
                view_type=preset["view_type"],
                name=preset["name"],
            )
            .one_or_none()
        )
        if exists is None:
            db.add(SavedView(**preset))
            inserted += 1
    db.flush()
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the default saved-view presets (idempotent by "
        "route_path + view_type + name)."
    )
    parser.parse_args()

    db = SessionLocal()
    try:
        inserted = seed_saved_views(db)
        db.commit()
        print(f"Seeded saved views: {inserted} inserted, {len(PRESETS) - inserted} already present.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
