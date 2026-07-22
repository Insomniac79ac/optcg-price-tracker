import Link from "next/link";
import type { ReactNode } from "react";

import { CollectionStatusBadge } from "@/components/CollectionStatusBadge";
import { GradingStatusBadge } from "@/components/GradingStatusBadge";
import { EmptyState } from "@/components/StateBlocks";
import {
  COLLECTION_STATUS_OPTIONS,
  updateCollectionItem,
  type CollectionItem,
  type PortfolioValuationItem,
  type ValuationMode,
} from "@/lib/api";
import { formatJpy } from "@/lib/format";
import { PriceCell } from "./PriceCell";

/** Card-detail "do I own this" panel - one row per collection item owned
 * for this card, joined against the matching /collection/valuation entries
 * (same source as /collection's own P&L, so the numbers never disagree).
 * `addAction` is the caller's existing "+ Add to collection" quick-add form
 * (unchanged, just slotted in here, always available so a second copy can
 * be added too) - this panel owns the layout, not the add-to-collection
 * form itself. Editing an existing item links out to /collection rather
 * than duplicating its edit form here; the status selector below is the one
 * inline mutation this panel does perform (existing PATCH /collection/{id},
 * not a new endpoint), matching the "mark status sell/hold/watch/grading"
 * ask directly. */
export function OwnershipSummaryPanel({
  items,
  valuationItems,
  valuationMode,
  onChanged,
  addAction,
}: {
  items: CollectionItem[];
  valuationItems: PortfolioValuationItem[];
  valuationMode: ValuationMode;
  onChanged?: () => void;
  addAction?: ReactNode;
}) {
  const valuationByItemId = new Map(valuationItems.map((v) => [v.collection_item_id, v]));

  async function handleStatusChange(itemId: number, status: string) {
    try {
      await updateCollectionItem(itemId, { status });
      onChanged?.();
    } catch {
      // Best-effort - the status badge simply won't update; no separate
      // error UI for this quick inline control (edit on /collection for
      // the full form with error handling).
    }
  }

  return (
    <div className="panel p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-text-primary">Ownership</h2>
        <Link href="/collection" className="text-xs text-sky-400 hover:text-sky-300">
          View collection →
        </Link>
      </div>

      {items.length === 0 && <EmptyState variant="inline">Not in collection yet.</EmptyState>}

      {items.length > 0 && (
        <div className="mb-3 space-y-3">
          {items.map((item) => {
            const valuation = valuationByItemId.get(item.id) ?? null;
            const currentValue =
              valuationMode === "graded_adjusted"
                ? (valuation?.graded_adjusted.value_jpy ?? null)
                : (valuation?.valuations.market_floor_value_jpy ?? null);
            const pnlJpy =
              valuationMode === "graded_adjusted"
                ? (valuation?.graded_adjusted.pnl_jpy ?? null)
                : (valuation?.valuations.pnl_vs_market_floor_jpy ?? null);
            const pnlPct =
              valuationMode === "graded_adjusted"
                ? (valuation?.graded_adjusted.pnl_pct ?? null)
                : (valuation?.valuations.pnl_vs_market_floor_pct ?? null);

            return (
              <div key={item.id} className="rounded-control border border-border-default bg-bg-page p-3">
                <div className="mb-2 flex flex-wrap items-center gap-3 text-sm">
                  <span className="mono font-medium text-text-primary">{item.quantity}×</span>
                  <span className="text-text-secondary">{item.condition_label ?? "raw"}</span>
                  <CollectionStatusBadge status={item.status} />
                  <select
                    value={item.status}
                    onChange={(e) => handleStatusChange(item.id, e.target.value)}
                    aria-label="Change status"
                    className="rounded-control border border-border-default bg-bg-surface px-1.5 py-0.5 text-[11px] text-text-secondary"
                  >
                    {COLLECTION_STATUS_OPTIONS.map((s) => (
                      <option key={s} value={s}>
                        Mark {s}
                      </option>
                    ))}
                  </select>
                  {item.latest_grading_status && (
                    <GradingStatusBadge status={item.latest_grading_status} />
                  )}
                  <Link
                    href={`/grading?item_id=${item.id}`}
                    className="text-xs font-medium text-violet-400 hover:text-violet-300"
                  >
                    Create grading submission
                  </Link>
                </div>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-text-secondary">
                      Purchase price
                    </div>
                    <div className="mono tabular text-sm text-text-primary">
                      {formatJpy(item.purchase_price_jpy)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-text-secondary">
                      Cost basis
                    </div>
                    <div className="mono tabular text-sm text-text-primary">
                      {valuation ? formatJpy(valuation.cost_basis_jpy) : "not available"}
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-text-secondary">
                      Current value
                    </div>
                    <PriceCell valueJpy={currentValue} mode={valuationMode} size="sm" />
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-text-secondary">
                      Unrealized P/L
                    </div>
                    <PriceCell valueJpy={pnlJpy} percent={pnlPct} signed size="sm" />
                  </div>
                </div>
                {(item.target_sell_price_jpy !== null || item.notes) && (
                  <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-text-muted">
                    {item.target_sell_price_jpy !== null && (
                      <span>Target sell: {formatJpy(item.target_sell_price_jpy)}</span>
                    )}
                    {item.notes && <span className="italic">{item.notes}</span>}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {addAction}
    </div>
  );
}
