"use client";

import { PortfolioInsightCards } from "@/components/PortfolioInsightCards";
import type { PortfolioValuation, ValuationMode } from "@/lib/api";
import { formatJpy, formatSignedJpy, formatSignedPct } from "@/lib/format";

/** Collection page's valuation mode toggle + stat grid + insights - split
 * out of app/collection/page.tsx (see that file's docstring-equivalent
 * comment) purely to shrink an otherwise very large single component; it's
 * still passed everything it needs as props rather than fetching anything
 * itself, so behavior is unchanged. */
export function CollectionValuationSummary({
  valuation,
  valuationStatus,
  valuationMode,
  onValuationModeChange,
  cardsMissingPrices,
}: {
  valuation: PortfolioValuation | null;
  valuationStatus: "loading" | "error" | "ready";
  valuationMode: ValuationMode;
  onValuationModeChange: (mode: ValuationMode) => void;
  cardsMissingPrices: number;
}) {
  return (
    <>
      <div className="mb-3 flex items-center gap-2">
        <span className="text-xs uppercase tracking-wide text-neutral-500">Valuation mode</span>
        <div className="flex gap-1">
          {(
            [
              { value: "raw_market", label: "Raw market" },
              { value: "graded_adjusted", label: "Graded adjusted" },
            ] as const
          ).map((opt) => (
            <button
              key={opt.value}
              onClick={() => onValuationModeChange(opt.value)}
              className={`rounded-control px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                valuationMode === opt.value
                  ? "bg-accent-gold text-black/80 ring-accent-gold"
                  : "bg-bg-surface text-text-muted ring-border-default hover:text-text-primary"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {valuationStatus === "loading" && (
        <div className="mb-6 rounded-lg border border-neutral-800 bg-neutral-900 p-4 text-center text-xs text-neutral-500">
          Loading valuation…
        </div>
      )}

      {valuationStatus === "error" && (
        <div className="mb-6 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          Failed to load portfolio valuation from the API.
        </div>
      )}

      {valuationStatus === "ready" && valuation && (
        <div className="mb-6 space-y-3">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <StatCard
              label="Total cost basis"
              value={formatJpy(valuation.summary.total_cost_basis_jpy)}
            />
            <StatCard
              label="Yuyu-Tei retail value"
              value={formatJpy(valuation.summary.retail_value_jpy)}
            />
            <StatCard
              label="Yuyu-Tei liquidation value"
              value={formatJpy(valuation.summary.liquidation_value_jpy)}
            />
            <StatCard
              label="SNKRDUNK market floor value"
              value={formatJpy(valuation.summary.market_floor_value_jpy)}
            />
            <StatCard
              label="Cards above target sell"
              value={valuation.summary.cards_above_target_sell}
            />
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <PnlStatCard
              label="P/L vs retail"
              jpy={valuation.summary.pnl_vs_retail_jpy}
              pct={valuation.summary.pnl_vs_retail_pct}
            />
            <PnlStatCard
              label="P/L vs liquidation"
              jpy={valuation.summary.pnl_vs_liquidation_jpy}
              pct={valuation.summary.pnl_vs_liquidation_pct}
            />
            <PnlStatCard
              label="P/L vs market floor"
              jpy={valuation.summary.pnl_vs_market_floor_jpy}
              pct={valuation.summary.pnl_vs_market_floor_pct}
            />
            <StatCard label="Cards missing prices" value={cardsMissingPrices} />
            <StatCard
              label="Items missing cost basis"
              value={valuation.summary.items_missing_cost_basis}
            />
          </div>
          {valuationMode === "graded_adjusted" && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <StatCard
                label="Graded-adjusted value"
                value={formatJpy(valuation.summary.graded_adjusted_value_jpy)}
              />
              <PnlStatCard
                label="P/L vs graded-adjusted"
                jpy={valuation.summary.pnl_vs_graded_adjusted_jpy}
                pct={valuation.summary.pnl_vs_graded_adjusted_pct}
              />
              <StatCard
                label="Items using graded value"
                value={valuation.summary.items_using_graded_value}
              />
              <StatCard
                label="Items using raw fallback"
                value={valuation.summary.items_using_raw_fallback}
              />
              <StatCard
                label="Items missing graded-adjusted value"
                value={valuation.summary.items_missing_graded_adjusted_value}
              />
            </div>
          )}
          <PortfolioInsightCards insights={valuation.summary.insights} />
        </div>
      )}
    </>
  );
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-neutral-100">{value}</div>
    </div>
  );
}

function PnlStatCard({ label, jpy, pct }: { label: string; jpy: number; pct: number }) {
  const tone = jpy > 0 ? "text-emerald-400" : jpy < 0 ? "text-rose-400" : "text-neutral-100";
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${tone}`}>{formatSignedJpy(jpy)}</div>
      <div className={`text-xs ${tone}`}>{formatSignedPct(pct)}</div>
    </div>
  );
}
