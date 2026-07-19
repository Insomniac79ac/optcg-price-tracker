import argparse
import sys

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import PortfolioValuationSnapshot
from app.services.cache import delete_cache_prefix
from app.services.job_locks import LockHeldError, with_job_lock
from app.services.portfolio_valuation import get_portfolio_valuation


def snapshot_portfolio_valuation(db: Session, *, skip_lock: bool = False) -> PortfolioValuationSnapshot:
    """Snapshots the current portfolio valuation summary (not the per-item
    breakdown) so its history can be tracked over time. Works for an empty
    collection too - get_portfolio_valuation returns a zero-value summary in
    that case, which is stored as-is rather than skipped.

    Acquires the 'portfolio_snapshot' concurrency lock for the call (see
    'Worker job concurrency locking' in docs/operations.md) - shared by this
    CLI's main(), POST /admin/actions/snapshot-portfolio, and the
    snapshot-portfolio step inside POST /admin/actions/full-market-refresh.
    skip_lock is test/dev-CLI only, never exposed to the admin UI/API.

    Always computed in graded_adjusted mode - that mode still includes every
    raw-market figure unchanged, plus the graded-adjusted ones, so one call
    is enough to populate both halves of the snapshot row."""
    with with_job_lock("portfolio_snapshot", skip_lock=skip_lock):
        return _snapshot_portfolio_valuation_locked(db)


def _snapshot_portfolio_valuation_locked(db: Session) -> PortfolioValuationSnapshot:
    summary = get_portfolio_valuation(db, valuation_mode="graded_adjusted").summary

    snapshot = PortfolioValuationSnapshot(
        total_items=summary.total_items,
        total_quantity=summary.total_quantity,
        total_cost_basis_jpy=summary.total_cost_basis_jpy,
        retail_value_jpy=summary.retail_value_jpy,
        liquidation_value_jpy=summary.liquidation_value_jpy,
        market_floor_value_jpy=summary.market_floor_value_jpy,
        pnl_vs_retail_jpy=summary.pnl_vs_retail_jpy,
        pnl_vs_liquidation_jpy=summary.pnl_vs_liquidation_jpy,
        pnl_vs_market_floor_jpy=summary.pnl_vs_market_floor_jpy,
        items_missing_yuyutei_sell=summary.items_missing_yuyutei_sell,
        items_missing_yuyutei_buy=summary.items_missing_yuyutei_buy,
        items_missing_snkrdunk_floor=summary.items_missing_snkrdunk_floor,
        items_missing_cost_basis=summary.items_missing_cost_basis,
        cards_above_target_sell=summary.cards_above_target_sell,
        graded_adjusted_value_jpy=summary.graded_adjusted_value_jpy,
        pnl_vs_graded_adjusted_jpy=summary.pnl_vs_graded_adjusted_jpy,
        items_using_graded_value=summary.items_using_graded_value,
        items_using_raw_fallback=summary.items_using_raw_fallback,
        items_missing_graded_adjusted_value=summary.items_missing_graded_adjusted_value,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    # See 'Cache invalidation' in docs/operations.md - a new snapshot changes
    # the dashboard's latest-snapshot widget and GET /collection/valuation/history.
    delete_cache_prefix("dashboard")
    delete_cache_prefix("collection_history")
    return snapshot


def print_report(snapshot: PortfolioValuationSnapshot) -> None:
    lines = [
        f"snapshot_id: {snapshot.id}",
        f"created_at: {snapshot.created_at}",
        f"total_items: {snapshot.total_items}",
        f"total_quantity: {snapshot.total_quantity}",
        f"total_cost_basis_jpy: {snapshot.total_cost_basis_jpy}",
        f"retail_value_jpy: {snapshot.retail_value_jpy}",
        f"liquidation_value_jpy: {snapshot.liquidation_value_jpy}",
        f"market_floor_value_jpy: {snapshot.market_floor_value_jpy}",
        f"pnl_vs_retail_jpy: {snapshot.pnl_vs_retail_jpy}",
        f"pnl_vs_liquidation_jpy: {snapshot.pnl_vs_liquidation_jpy}",
        f"pnl_vs_market_floor_jpy: {snapshot.pnl_vs_market_floor_jpy}",
        f"items_missing_yuyutei_sell: {snapshot.items_missing_yuyutei_sell}",
        f"items_missing_yuyutei_buy: {snapshot.items_missing_yuyutei_buy}",
        f"items_missing_snkrdunk_floor: {snapshot.items_missing_snkrdunk_floor}",
        f"items_missing_cost_basis: {snapshot.items_missing_cost_basis}",
        f"cards_above_target_sell: {snapshot.cards_above_target_sell}",
        f"graded_adjusted_value_jpy: {snapshot.graded_adjusted_value_jpy}",
        f"pnl_vs_graded_adjusted_jpy: {snapshot.pnl_vs_graded_adjusted_jpy}",
        f"items_using_graded_value: {snapshot.items_using_graded_value}",
        f"items_using_raw_fallback: {snapshot.items_using_raw_fallback}",
        f"items_missing_graded_adjusted_value: {snapshot.items_missing_graded_adjusted_value}",
    ]
    for line in lines:
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Take a snapshot of the current portfolio valuation summary and store it."
    )
    parser.add_argument(
        "--skip-lock", action="store_true",
        help="Skip the portfolio_snapshot concurrency lock. Test/dev only - never use in production.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        try:
            snapshot = snapshot_portfolio_valuation(db, skip_lock=args.skip_lock)
        except LockHeldError as exc:
            print(f"Job already running: {exc.lock_name}")
            sys.exit(2)
    finally:
        db.close()

    print_report(snapshot)


if __name__ == "__main__":
    main()
