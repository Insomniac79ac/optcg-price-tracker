"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { CollectionAnalyticsBreakdownTable } from "@/components/CollectionAnalyticsBreakdownTable";
import { CollectionStatusBadge } from "@/components/CollectionStatusBadge";
import { RarityBadge } from "@/components/RarityBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { TableScrollContainer } from "@/components/ui/DataTableShell";
import { SavedViewBar } from "@/components/ui/SavedViewBar";
import { StatCard, type StatTone } from "@/components/ui/StatCard";
import {
  AdminAuthRequiredError,
  type CollectionAnalytics,
  type ValuationMode,
  fetchCollectionAnalytics,
} from "@/lib/api";
import { cardDisplayName, formatJPY, formatNumber, formatPercent, formatSignedJpy } from "@/lib/format";

// Dynamically imported (recharts is a sizeable chunk) so pages that don't
// visit collection analytics never pay for it - same rationale/pattern as
// DashboardPortfolioChart. ssr: false sidesteps recharts' SSR/hydration
// mismatch (it measures its container via ResizeObserver).
const CollectionAnalyticsBreakdownChart = dynamic(
  () =>
    import("@/components/CollectionAnalyticsBreakdownChart").then(
      (mod) => mod.CollectionAnalyticsBreakdownChart,
    ),
  { ssr: false, loading: () => <LoadingState>Loading chart…</LoadingState> },
);

const VALUATION_MODE_OPTIONS = [
  { value: "raw_market", label: "Raw market" },
  { value: "graded_adjusted", label: "Graded adjusted" },
] as const;

type PageStatus = "loading" | "unauthorized" | "error" | "ready";

export default function CollectionAnalyticsPage() {
  const [data, setData] = useState<CollectionAnalytics | null>(null);
  const [status, setStatus] = useState<PageStatus>("loading");
  const [valuationMode, setValuationMode] = useState<ValuationMode>("raw_market");
  const [includeSold, setIncludeSold] = useState(false);

  useEffect(() => {
    setStatus("loading");
    fetchCollectionAnalytics({ valuation_mode: valuationMode, include_sold: includeSold })
      .then((res) => {
        setData(res);
        setStatus("ready");
      })
      .catch((err) => {
        setStatus(err instanceof AdminAuthRequiredError ? "unauthorized" : "error");
      });
  }, [valuationMode, includeSold]);

  const isEmpty = status === "ready" && data !== null && data.summary.total_items === 0;

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-1 flex items-baseline gap-3">
          <h1 className="text-lg font-semibold text-text-primary">Collection Analytics</h1>
          <Link
            href="/collection"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Collection →
          </Link>
          <Link
            href="/analytics/wishlist"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Wishlist Analytics →
          </Link>
          <Link
            href="/analytics/sell-decisions"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Sell Decision Support →
          </Link>
          <Link
            href="/analytics/grading"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Grading ROI Analytics →
          </Link>
          <Link
            href="/analytics/portfolio-risk"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Portfolio Risk →
          </Link>
          <Link
            href="/analytics/digest"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Digest →
          </Link>
        </div>
        <p className="mb-4 text-sm text-text-muted">
          Composition, valuation exposure, and concentration risk.
        </p>

        <div className="mb-6 flex flex-wrap items-center gap-4">
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-muted">
              Valuation mode
            </label>
            <div className="flex overflow-hidden rounded border border-border-default text-xs">
              {VALUATION_MODE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setValuationMode(opt.value)}
                  className={`px-2.5 py-1 ${
                    valuationMode === opt.value
                      ? "bg-sky-500/20 text-sky-300"
                      : "bg-bg-surface text-text-secondary hover:text-text-primary"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
          <label className="flex items-center gap-2 text-xs text-text-secondary">
            <input
              type="checkbox"
              checked={includeSold}
              onChange={(e) => setIncludeSold(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-border-default bg-bg-surface"
            />
            Include sold items
          </label>
        </div>

        <SavedViewBar
          routePath="/analytics/collection"
          viewType="analytics_collection"
          scope="analytics"
          currentFilters={{ valuationMode, includeSold }}
          onApply={(filters) => {
            if (typeof filters.valuationMode === "string")
              setValuationMode(filters.valuationMode as ValuationMode);
            if (typeof filters.includeSold === "boolean") setIncludeSold(filters.includeSold);
          }}
        />

        {status === "loading" && <LoadingState>Loading collection analytics…</LoadingState>}
        {status === "unauthorized" && (
          <ErrorState>Sign in to view your collection analytics.</ErrorState>
        )}
        {status === "error" && (
          <ErrorState>Failed to load collection analytics from the API.</ErrorState>
        )}

        {status === "ready" && data && isEmpty && (
          <EmptyState>No collection analytics yet. Add cards to your collection first.</EmptyState>
        )}

        {status === "ready" && data && !isEmpty && (
          <>
            <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <StatCard label="Total items" value={formatNumber(data.summary.total_items)} />
              <StatCard label="Total quantity" value={formatNumber(data.summary.total_quantity)} />
              <StatCard label="Total cost basis" value={formatJPY(data.summary.total_cost_basis_jpy)} />
              <StatCard
                label="Raw market floor value"
                value={formatJPY(data.summary.raw_market_floor_value_jpy)}
              />
              <StatCard
                label="Graded adjusted value"
                value={formatJPY(data.summary.graded_adjusted_value_jpy)}
              />
              <StatCard
                label="Unrealized P/L"
                value={formatSignedJpy(data.summary.unrealized_pnl_jpy)}
                tone={pnlTone(data.summary.unrealized_pnl_jpy)}
                hint={formatPercent(data.summary.unrealized_pnl_pct)}
              />
              <StatCard
                label="Items missing cost basis"
                value={formatNumber(data.summary.items_missing_cost_basis)}
                tone={data.summary.items_missing_cost_basis > 0 ? "bad" : undefined}
              />
              <StatCard
                label="Items missing market price"
                value={formatNumber(data.summary.items_missing_market_price)}
                tone={data.summary.items_missing_market_price > 0 ? "bad" : undefined}
              />
              <StatCard
                label="Wishlist unique cards"
                value={formatNumber(data.summary.wishlist_unique_cards)}
              />
              <StatCard
                label="Active grading submissions"
                value={formatNumber(data.summary.grading_active_count)}
              />
            </div>

            <Section title="By set">
              <div className="mb-3">
                <CollectionAnalyticsBreakdownChart rows={data.breakdowns.by_set} />
              </div>
              <CollectionAnalyticsBreakdownTable
                rows={data.breakdowns.by_set}
                firstColumnLabel="Set"
                columns={["quantity", "value", "weight", "pnl_pct"]}
              />
            </Section>

            <Section title="By rarity">
              <div className="mb-3">
                <CollectionAnalyticsBreakdownChart rows={data.breakdowns.by_rarity} />
              </div>
              <CollectionAnalyticsBreakdownTable
                rows={data.breakdowns.by_rarity}
                firstColumnLabel="Rarity"
                columns={["quantity", "value", "weight", "pnl_pct"]}
              />
            </Section>

            <Section title="By variant">
              <CollectionAnalyticsBreakdownTable
                rows={data.breakdowns.by_variant}
                firstColumnLabel="Variant"
                columns={["quantity", "value", "weight"]}
              />
            </Section>

            <Section title="By status">
              <CollectionAnalyticsBreakdownTable
                rows={data.breakdowns.by_status}
                firstColumnLabel="Status"
                columns={["item_count", "value", "weight"]}
              />
            </Section>

            <Section title="By tag">
              <CollectionAnalyticsBreakdownTable
                rows={data.breakdowns.by_tag}
                firstColumnLabel="Tag"
                columns={["item_count", "value", "pnl_jpy", "weight"]}
              />
            </Section>

            <Section title="By group">
              <CollectionAnalyticsBreakdownTable
                rows={data.breakdowns.by_group}
                firstColumnLabel="Group"
                columns={["item_count", "value", "pnl_jpy", "weight"]}
              />
            </Section>

            <Section title="By grading status">
              <CollectionAnalyticsBreakdownTable
                rows={data.breakdowns.by_grading_status}
                firstColumnLabel="Grading status"
                columns={["item_count", "value"]}
              />
            </Section>

            <Section title="Concentration risk">
              <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <StatCard
                  label="Top 10 cards value %"
                  value={formatPercent(data.concentration.top_10_cards_value_pct)}
                />
                <StatCard
                  label="Largest single card value %"
                  value={formatPercent(data.concentration.largest_single_card_value_pct)}
                />
                <StatCard
                  label="Largest set exposure"
                  value={
                    data.concentration.largest_set_exposure
                      ? `${data.concentration.largest_set_exposure.label} (${formatPercent(
                          data.concentration.largest_set_exposure.portfolio_weight_pct,
                        )})`
                      : "not available"
                  }
                />
                <StatCard
                  label="Largest rarity exposure"
                  value={
                    data.concentration.largest_rarity_exposure
                      ? `${data.concentration.largest_rarity_exposure.label} (${formatPercent(
                          data.concentration.largest_rarity_exposure.portfolio_weight_pct,
                        )})`
                      : "not available"
                  }
                />
              </div>

              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
                Top 5 cards by value
              </h3>
              {data.concentration.top_5_cards_by_value.length === 0 ? (
                <EmptyState variant="inline">No data available.</EmptyState>
              ) : (
                <TableScrollContainer showScrollHint={false}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Card</th>
                        <th>Set</th>
                        <th>Rarity</th>
                        <th className="text-right">Value</th>
                        <th className="text-right">Weight %</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.concentration.top_5_cards_by_value.map((card) => (
                        <tr key={card.collection_item_id}>
                          <td>
                            <Link
                              href={`/cards/${card.card_id}`}
                              className="text-sky-400 hover:text-sky-300"
                            >
                              {card.card_code} · {cardDisplayName(card)}
                            </Link>
                          </td>
                          <td className="text-text-secondary">{card.set_code}</td>
                          <td>
                            <RarityBadge rarity={card.rarity} />
                          </td>
                          <td className="mono tabular text-right">{formatJPY(card.value_jpy)}</td>
                          <td className="mono tabular text-right">
                            {formatPercent(card.portfolio_weight_pct)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableScrollContainer>
              )}
            </Section>

            <Section title="Cost basis">
              <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <StatCard
                  label="Items with cost basis"
                  value={formatNumber(data.cost_basis.items_with_cost_basis)}
                />
                <StatCard
                  label="Items without cost basis"
                  value={formatNumber(data.cost_basis.items_without_cost_basis)}
                />
                <StatCard
                  label="Average cost basis"
                  value={formatJPY(data.cost_basis.average_cost_basis_jpy)}
                />
                <StatCard
                  label="Median cost basis"
                  value={formatJPY(data.cost_basis.median_cost_basis_jpy)}
                />
              </div>

              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
                Highest cost basis items
              </h3>
              {data.cost_basis.highest_cost_basis_items.length === 0 ? (
                <EmptyState variant="inline">No data available.</EmptyState>
              ) : (
                <TableScrollContainer showScrollHint={false}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Card</th>
                        <th className="text-right">Purchase price</th>
                        <th className="text-right">Quantity</th>
                        <th className="text-right">Cost basis</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.cost_basis.highest_cost_basis_items.map((item) => (
                        <tr key={item.collection_item_id}>
                          <td>
                            <Link
                              href={`/cards/${item.card_id}`}
                              className="text-sky-400 hover:text-sky-300"
                            >
                              {item.card_code} · {cardDisplayName(item)}
                            </Link>
                          </td>
                          <td className="mono tabular text-right">
                            {formatJPY(item.purchase_price_jpy)}
                          </td>
                          <td className="mono tabular text-right">{formatNumber(item.quantity)}</td>
                          <td className="mono tabular text-right">{formatJPY(item.cost_basis_jpy)}</td>
                          <td>
                            <CollectionStatusBadge status={item.status} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableScrollContainer>
              )}
            </Section>

            <Section title="Valuation quality">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                <StatCard
                  label="Items with Yuyu-Tei sell"
                  value={formatNumber(data.valuation_quality.items_with_yuyutei_sell)}
                />
                <StatCard
                  label="Items with Yuyu-Tei buy"
                  value={formatNumber(data.valuation_quality.items_with_yuyutei_buy)}
                />
                <StatCard
                  label="Items with SNKRDUNK floor"
                  value={formatNumber(data.valuation_quality.items_with_snkrdunk_floor)}
                />
                <StatCard
                  label="Items using graded value"
                  value={formatNumber(data.valuation_quality.items_using_graded_value)}
                />
                <StatCard
                  label="Items using raw fallback"
                  value={formatNumber(data.valuation_quality.items_using_raw_fallback)}
                />
                <StatCard
                  label="Coverage %"
                  value={formatPercent(data.valuation_quality.coverage_pct)}
                />
              </div>
            </Section>
          </>
        )}
      </main>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="mb-2 text-sm font-semibold text-text-primary">{title}</h2>
      {children}
    </section>
  );
}

function pnlTone(jpy: number): StatTone {
  if (jpy > 0) return "good";
  if (jpy < 0) return "bad";
  return "neutral";
}
