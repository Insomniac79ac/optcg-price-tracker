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
          <h1 className="text-lg font-semibold text-neutral-100">Collection Analytics</h1>
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
        </div>
        <p className="mb-4 text-sm text-neutral-500">
          Composition, valuation exposure, and concentration risk.
        </p>

        <div className="mb-6 flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-xs uppercase tracking-wide text-neutral-500">Valuation mode</span>
            <div className="flex gap-1">
              {VALUATION_MODE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setValuationMode(opt.value)}
                  className={`rounded px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                    valuationMode === opt.value
                      ? "bg-neutral-100 text-neutral-900 ring-neutral-100"
                      : "bg-neutral-900 text-neutral-400 ring-neutral-800 hover:text-neutral-100"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
          <label className="flex items-center gap-2 text-xs text-neutral-400">
            <input
              type="checkbox"
              checked={includeSold}
              onChange={(e) => setIncludeSold(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-neutral-700 bg-neutral-900"
            />
            Include sold items
          </label>
        </div>

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
              <PnlStatCard
                label="Unrealized P/L"
                jpy={data.summary.unrealized_pnl_jpy}
                pct={data.summary.unrealized_pnl_pct}
              />
              <StatCard
                label="Items missing cost basis"
                value={formatNumber(data.summary.items_missing_cost_basis)}
                tone={data.summary.items_missing_cost_basis > 0 ? "warning" : undefined}
              />
              <StatCard
                label="Items missing market price"
                value={formatNumber(data.summary.items_missing_market_price)}
                tone={data.summary.items_missing_market_price > 0 ? "warning" : undefined}
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
                  size="sm"
                  label="Top 10 cards value %"
                  value={formatPercent(data.concentration.top_10_cards_value_pct)}
                />
                <StatCard
                  size="sm"
                  label="Largest single card value %"
                  value={formatPercent(data.concentration.largest_single_card_value_pct)}
                />
                <StatCard
                  size="sm"
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
                  size="sm"
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

              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
                Top 5 cards by value
              </h3>
              {data.concentration.top_5_cards_by_value.length === 0 ? (
                <EmptyState variant="inline">No data available.</EmptyState>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-neutral-800">
                  <table className="w-full min-w-[560px] border-collapse text-xs">
                    <thead>
                      <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                        <th className="px-3 py-2 font-medium">Card</th>
                        <th className="px-3 py-2 font-medium">Set</th>
                        <th className="px-3 py-2 font-medium">Rarity</th>
                        <th className="px-3 py-2 text-right font-medium">Value</th>
                        <th className="px-3 py-2 text-right font-medium">Weight %</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.concentration.top_5_cards_by_value.map((card) => (
                        <tr
                          key={card.collection_item_id}
                          className="border-b border-neutral-900 last:border-0"
                        >
                          <td className="px-3 py-2 text-neutral-200">
                            <Link
                              href={`/cards/${card.card_id}`}
                              className="text-sky-400 hover:text-sky-300"
                            >
                              {card.card_code} · {cardDisplayName(card)}
                            </Link>
                          </td>
                          <td className="px-3 py-2 text-neutral-300">{card.set_code}</td>
                          <td className="px-3 py-2">
                            <RarityBadge rarity={card.rarity} />
                          </td>
                          <td className="px-3 py-2 text-right text-neutral-300">
                            {formatJPY(card.value_jpy)}
                          </td>
                          <td className="px-3 py-2 text-right text-neutral-300">
                            {formatPercent(card.portfolio_weight_pct)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>

            <Section title="Cost basis">
              <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <StatCard
                  size="sm"
                  label="Items with cost basis"
                  value={formatNumber(data.cost_basis.items_with_cost_basis)}
                />
                <StatCard
                  size="sm"
                  label="Items without cost basis"
                  value={formatNumber(data.cost_basis.items_without_cost_basis)}
                />
                <StatCard
                  size="sm"
                  label="Average cost basis"
                  value={formatJPY(data.cost_basis.average_cost_basis_jpy)}
                />
                <StatCard
                  size="sm"
                  label="Median cost basis"
                  value={formatJPY(data.cost_basis.median_cost_basis_jpy)}
                />
              </div>

              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
                Highest cost basis items
              </h3>
              {data.cost_basis.highest_cost_basis_items.length === 0 ? (
                <EmptyState variant="inline">No data available.</EmptyState>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-neutral-800">
                  <table className="w-full min-w-[620px] border-collapse text-xs">
                    <thead>
                      <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                        <th className="px-3 py-2 font-medium">Card</th>
                        <th className="px-3 py-2 text-right font-medium">Purchase price</th>
                        <th className="px-3 py-2 text-right font-medium">Quantity</th>
                        <th className="px-3 py-2 text-right font-medium">Cost basis</th>
                        <th className="px-3 py-2 font-medium">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.cost_basis.highest_cost_basis_items.map((item) => (
                        <tr
                          key={item.collection_item_id}
                          className="border-b border-neutral-900 last:border-0"
                        >
                          <td className="px-3 py-2 text-neutral-200">
                            <Link
                              href={`/cards/${item.card_id}`}
                              className="text-sky-400 hover:text-sky-300"
                            >
                              {item.card_code} · {cardDisplayName(item)}
                            </Link>
                          </td>
                          <td className="px-3 py-2 text-right text-neutral-300">
                            {formatJPY(item.purchase_price_jpy)}
                          </td>
                          <td className="px-3 py-2 text-right text-neutral-300">
                            {formatNumber(item.quantity)}
                          </td>
                          <td className="px-3 py-2 text-right text-neutral-300">
                            {formatJPY(item.cost_basis_jpy)}
                          </td>
                          <td className="px-3 py-2">
                            <CollectionStatusBadge status={item.status} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>

            <Section title="Valuation quality">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                <StatCard
                  size="sm"
                  label="Items with Yuyu-Tei sell"
                  value={formatNumber(data.valuation_quality.items_with_yuyutei_sell)}
                />
                <StatCard
                  size="sm"
                  label="Items with Yuyu-Tei buy"
                  value={formatNumber(data.valuation_quality.items_with_yuyutei_buy)}
                />
                <StatCard
                  size="sm"
                  label="Items with SNKRDUNK floor"
                  value={formatNumber(data.valuation_quality.items_with_snkrdunk_floor)}
                />
                <StatCard
                  size="sm"
                  label="Items using graded value"
                  value={formatNumber(data.valuation_quality.items_using_graded_value)}
                />
                <StatCard
                  size="sm"
                  label="Items using raw fallback"
                  value={formatNumber(data.valuation_quality.items_using_raw_fallback)}
                />
                <StatCard
                  size="sm"
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
      <h2 className="mb-2 text-sm font-semibold text-neutral-200">{title}</h2>
      {children}
    </section>
  );
}

function StatCard({
  label,
  value,
  tone,
  size = "lg",
}: {
  label: string;
  value: number | string;
  tone?: "warning";
  size?: "lg" | "sm";
}) {
  const valueSizeClass = size === "lg" ? "text-2xl" : "text-lg";
  const toneClass = tone === "warning" ? "text-amber-400" : "text-neutral-100";
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className={`mt-1 font-semibold ${valueSizeClass} ${toneClass}`}>{value}</div>
    </div>
  );
}

function PnlStatCard({ label, jpy, pct }: { label: string; jpy: number; pct: number }) {
  const tone = jpy > 0 ? "text-emerald-400" : jpy < 0 ? "text-rose-400" : "text-neutral-100";
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${tone}`}>{formatSignedJpy(jpy)}</div>
      <div className={`text-xs ${tone}`}>{formatPercent(pct)}</div>
    </div>
  );
}
