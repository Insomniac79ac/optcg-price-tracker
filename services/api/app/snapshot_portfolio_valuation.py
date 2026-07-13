import argparse

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import PortfolioValuationSnapshot
from app.services.portfolio_valuation import get_portfolio_valuation


def snapshot_portfolio_valuation(db: Session) -> PortfolioValuationSnapshot:
    """Snapshots the current portfolio valuation summary (not the per-item
    breakdown) so its history can be tracked over time. Works for an empty
    collection too - get_portfolio_valuation returns a zero-value summary in
    that case, which is stored as-is rather than skipped.

    Always computed in graded_adjusted mode - that mode still includes every
    raw-market figure unchanged, plus the graded-adjusted ones, so one call
    is enough to populate both halves of the snapshot row."""
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
    argparse.ArgumentParser(
        description="Take a snapshot of the current portfolio valuation summary and store it."
    ).parse_args()

    db = SessionLocal()
    try:
        snapshot = snapshot_portfolio_valuation(db)
    finally:
        db.close()

    print_report(snapshot)


if __name__ == "__main__":
    main()
