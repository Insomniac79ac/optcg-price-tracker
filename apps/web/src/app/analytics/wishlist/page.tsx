"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { WishlistAnalyticsBreakdownTable } from "@/components/WishlistAnalyticsBreakdownTable";
import { WishlistAnalyticsTargetTable } from "@/components/WishlistAnalyticsTargetTable";
import { SavedViewBar } from "@/components/ui/SavedViewBar";
import { StatCard } from "@/components/ui/StatCard";
import { AdminAuthRequiredError, type WishlistAnalytics, fetchWishlistAnalytics } from "@/lib/api";
import { formatJPY, formatNumber, formatPercent, formatSignedJpy } from "@/lib/format";

// Dynamically imported (recharts is a sizeable chunk) so pages that don't
// visit wishlist analytics never pay for it - same pattern as
// DashboardPortfolioChart / CollectionAnalyticsBreakdownChart.
const WishlistAnalyticsBreakdownChart = dynamic(
  () =>
    import("@/components/WishlistAnalyticsBreakdownChart").then(
      (mod) => mod.WishlistAnalyticsBreakdownChart,
    ),
  { ssr: false, loading: () => <LoadingState>Loading chart…</LoadingState> },
);

type PageStatus = "loading" | "unauthorized" | "error" | "ready";

export default function WishlistAnalyticsPage() {
  const [data, setData] = useState<WishlistAnalytics | null>(null);
  const [status, setStatus] = useState<PageStatus>("loading");
  const [includeRemoved, setIncludeRemoved] = useState(false);
  const [includePurchased, setIncludePurchased] = useState(false);

  useEffect(() => {
    setStatus("loading");
    fetchWishlistAnalytics({ include_removed: includeRemoved, include_purchased: includePurchased })
      .then((res) => {
        setData(res);
        setStatus("ready");
      })
      .catch((err) => {
        setStatus(err instanceof AdminAuthRequiredError ? "unauthorized" : "error");
      });
  }, [includeRemoved, includePurchased]);

  const isEmpty = status === "ready" && data !== null && data.summary.total_items === 0;

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-1 flex items-baseline gap-3">
          <h1 className="text-lg font-semibold text-text-primary">Wishlist Analytics</h1>
          <Link
            href="/wishlist"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Wishlist →
          </Link>
          <Link
            href="/analytics/collection"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Collection Analytics →
          </Link>
          <Link
            href="/analytics/buy-decisions"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Buy Decision Support →
          </Link>
          <Link
            href="/analytics/digest"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Digest →
          </Link>
        </div>
        <p className="mb-4 text-sm text-text-muted">
          Budget planning, target hits, and acquisition priorities.
        </p>

        <div className="mb-6 flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-xs text-text-secondary">
            <input
              type="checkbox"
              checked={includeRemoved}
              onChange={(e) => setIncludeRemoved(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-border-default bg-bg-surface"
            />
            Include removed
          </label>
          <label className="flex items-center gap-2 text-xs text-text-secondary">
            <input
              type="checkbox"
              checked={includePurchased}
              onChange={(e) => setIncludePurchased(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-border-default bg-bg-surface"
            />
            Include purchased
          </label>
        </div>

        <SavedViewBar
          routePath="/analytics/wishlist"
          viewType="analytics_wishlist"
          scope="analytics"
          currentFilters={{ includeRemoved, includePurchased }}
          onApply={(filters) => {
            if (typeof filters.includeRemoved === "boolean") setIncludeRemoved(filters.includeRemoved);
            if (typeof filters.includePurchased === "boolean")
              setIncludePurchased(filters.includePurchased);
          }}
        />

        {status === "loading" && <LoadingState>Loading wishlist analytics…</LoadingState>}
        {status === "unauthorized" && (
          <ErrorState>Sign in to view your wishlist analytics.</ErrorState>
        )}
        {status === "error" && (
          <ErrorState>Failed to load wishlist analytics from the API.</ErrorState>
        )}

        {status === "ready" && data && isEmpty && (
          <EmptyState>No wishlist analytics yet. Add cards to your wishlist first.</EmptyState>
        )}

        {status === "ready" && data && !isEmpty && (
          <>
            <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <StatCard label="Total wishlist items" value={formatNumber(data.summary.total_items)} />
              <StatCard label="Watching" value={formatNumber(data.summary.watching_count)} />
              <StatCard
                label="Target hits"
                value={formatNumber(data.summary.target_hit_count)}
                tone={data.summary.target_hit_count > 0 ? "good" : undefined}
              />
              <StatCard label="Grails" value={formatNumber(data.summary.grail_count)} />
              <StatCard label="High priority" value={formatNumber(data.summary.high_priority_count)} />
              <StatCard
                label="Owned already"
                value={formatNumber(data.summary.owned_already_count)}
              />
              <StatCard
                label="Total target budget"
                value={formatJPY(data.summary.total_target_budget_jpy)}
              />
              <StatCard label="Total max budget" value={formatJPY(data.summary.total_max_budget_jpy)} />
              <StatCard
                label="Current price total"
                value={formatJPY(data.summary.total_current_price_jpy)}
              />
              <StatCard
                label="Budget gap to target"
                value={formatSignedJpy(data.summary.budget_gap_to_target_jpy)}
                tone={
                  data.summary.budget_gap_to_target_jpy > 0
                    ? "bad"
                    : data.summary.budget_gap_to_target_jpy < 0
                      ? "good"
                      : undefined
                }
              />
              <StatCard
                label="Price coverage %"
                value={formatPercent(data.price_coverage.coverage_pct)}
              />
            </div>

            <Section title="Budget plan">
              <SubSection title="Grail targets">
                <WishlistAnalyticsTargetTable
                  items={data.budget_plan.grail_targets}
                  columns={["priority", "set_rarity", "quantities", "target_price", "max_price", "current_price", "gap", "target_hit"]}
                />
              </SubSection>
              <SubSection title="High priority targets">
                <WishlistAnalyticsTargetTable
                  items={data.budget_plan.high_priority_targets}
                  columns={["priority", "set_rarity", "quantities", "target_price", "max_price", "current_price", "gap", "target_hit"]}
                />
              </SubSection>
              <SubSection title="Best gap to target">
                <WishlistAnalyticsTargetTable
                  items={data.budget_plan.best_gap_to_target}
                  columns={["priority", "set_rarity", "quantities", "target_price", "max_price", "current_price", "gap", "target_hit"]}
                />
              </SubSection>
              <SubSection title="Largest budget items">
                <WishlistAnalyticsTargetTable
                  items={data.budget_plan.largest_budget_items}
                  columns={["priority", "set_rarity", "quantities", "target_price", "max_price", "current_price", "gap", "target_hit"]}
                />
              </SubSection>
              <SubSection title="Already owned" last>
                <WishlistAnalyticsTargetTable
                  items={data.budget_plan.already_owned}
                  columns={["priority", "set_rarity", "quantities", "target_price", "max_price", "current_price", "gap", "target_hit"]}
                />
              </SubSection>
            </Section>

            <Section title="By priority">
              <div className="mb-3">
                <WishlistAnalyticsBreakdownChart rows={data.breakdowns.by_priority} />
              </div>
              <WishlistAnalyticsBreakdownTable
                rows={data.breakdowns.by_priority}
                firstColumnLabel="Priority"
                columns={["item_count", "desired_quantity", "target_budget_jpy", "target_hit_count", "budget_weight_pct"]}
              />
            </Section>

            <Section title="By status">
              <div className="mb-3">
                <WishlistAnalyticsBreakdownChart rows={data.breakdowns.by_status} />
              </div>
              <WishlistAnalyticsBreakdownTable
                rows={data.breakdowns.by_status}
                firstColumnLabel="Status"
                columns={["item_count", "desired_quantity", "target_budget_jpy", "target_hit_count", "budget_weight_pct"]}
              />
            </Section>

            <Section title="By set">
              <WishlistAnalyticsBreakdownTable
                rows={data.breakdowns.by_set}
                firstColumnLabel="Set"
                columns={["item_count", "desired_quantity", "target_budget_jpy", "current_price_jpy", "budget_weight_pct"]}
              />
            </Section>

            <Section title="By rarity">
              <WishlistAnalyticsBreakdownTable
                rows={data.breakdowns.by_rarity}
                firstColumnLabel="Rarity"
                columns={["item_count", "desired_quantity", "target_budget_jpy", "current_price_jpy", "budget_weight_pct"]}
              />
            </Section>

            <Section title="By preferred source">
              <WishlistAnalyticsBreakdownTable
                rows={data.breakdowns.by_preferred_source}
                firstColumnLabel="Preferred source"
                columns={["item_count", "desired_quantity", "target_budget_jpy", "budget_weight_pct"]}
              />
            </Section>

            <Section title="By preferred condition">
              <WishlistAnalyticsBreakdownTable
                rows={data.breakdowns.by_preferred_condition}
                firstColumnLabel="Preferred condition"
                columns={["item_count", "desired_quantity", "target_budget_jpy", "budget_weight_pct"]}
              />
            </Section>

            <Section title="Target hits">
              <WishlistAnalyticsTargetTable
                items={data.target_hits}
                columns={["priority", "quantities", "target_price", "current_price", "source", "gap"]}
              />
            </Section>

            <Section title="Price coverage" last>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <StatCard
                  label="Items with current price"
                  value={formatNumber(data.price_coverage.items_with_current_price)}
                />
                <StatCard
                  label="Items missing current price"
                  value={formatNumber(data.price_coverage.items_missing_current_price)}
                  tone={data.price_coverage.items_missing_current_price > 0 ? "bad" : undefined}
                />
                <StatCard
                  label="Coverage %"
                  value={formatPercent(data.price_coverage.coverage_pct)}
                />
              </div>
            </Section>
          </>
        )}
      </main>
    </div>
  );
}

function Section({ title, children, last = false }: { title: string; children: ReactNode; last?: boolean }) {
  return (
    <section className={last ? "mb-2" : "mb-8"}>
      <h2 className="mb-2 text-sm font-semibold text-text-primary">{title}</h2>
      {children}
    </section>
  );
}

function SubSection({
  title,
  children,
  last = false,
}: {
  title: string;
  children: ReactNode;
  last?: boolean;
}) {
  return (
    <div className={last ? "mb-0" : "mb-4"}>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">{title}</h3>
      {children}
    </div>
  );
}
