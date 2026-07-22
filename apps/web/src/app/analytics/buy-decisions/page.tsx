"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { BuyDecisionActionGroups } from "@/components/BuyDecisionActionGroups";
import { BuyDecisionCandidateTable } from "@/components/BuyDecisionCandidateTable";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { ActionButton } from "@/components/ui/ActionButton";
import { StatCard as SharedStatCard, type StatTone } from "@/components/ui/StatCard";
import {
  AdminAuthRequiredError,
  fetchBuyDecisions,
  type BuyDecisionAction,
  type BuyDecisionPriorityFilter,
  type BuyDecisionSupport,
  type BuySourcePreference,
} from "@/lib/api";
import { formatJPY, formatNumber, formatSignedJpy } from "@/lib/format";

type PageStatus = "loading" | "unauthorized" | "error" | "ready";

const SOURCE_OPTIONS: { value: BuySourcePreference; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "snkrdunk", label: "SNKRDUNK" },
  { value: "yuyutei", label: "Yuyu-Tei" },
];

const ACTION_OPTIONS: { value: BuyDecisionAction | "all"; label: string }[] = [
  { value: "all", label: "All actions" },
  { value: "review_buy", label: "Review buy" },
  { value: "wait", label: "Wait" },
  { value: "skip", label: "Skip" },
  { value: "missing_data", label: "Missing data" },
  { value: "monitor", label: "Monitor" },
];

const PRIORITY_OPTIONS: { value: BuyDecisionPriorityFilter | "all"; label: string }[] = [
  { value: "all", label: "All priorities" },
  { value: "grail", label: "Grail" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
];

const LIMIT_OPTIONS = [25, 50, 100, 200];

export default function BuyDecisionsPage() {
  const [data, setData] = useState<BuyDecisionSupport | null>(null);
  const [status, setStatus] = useState<PageStatus>("loading");
  const [sourcePreference, setSourcePreference] = useState<BuySourcePreference>("auto");
  const [includeOwned, setIncludeOwned] = useState(false);
  const [includePurchased, setIncludePurchased] = useState(false);
  const [minScore, setMinScore] = useState<string>("");
  const [action, setAction] = useState<BuyDecisionAction | "all">("all");
  const [priority, setPriority] = useState<BuyDecisionPriorityFilter | "all">("all");
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);

  const load = useCallback(() => {
    setStatus("loading");
    fetchBuyDecisions({
      source_preference: sourcePreference,
      include_owned: includeOwned,
      include_purchased: includePurchased,
      min_score: minScore.trim() === "" ? undefined : Number(minScore),
      action: action === "all" ? undefined : action,
      priority: priority === "all" ? undefined : priority,
      limit,
      offset,
    })
      .then((res) => {
        setData(res);
        setStatus("ready");
      })
      .catch((err) => {
        setStatus(err instanceof AdminAuthRequiredError ? "unauthorized" : "error");
      });
  }, [sourcePreference, includeOwned, includePurchased, minScore, action, priority, limit, offset]);

  useEffect(() => {
    load();
  }, [load]);

  // Any filter change other than pagination itself resets back to page 1.
  useEffect(() => {
    setOffset(0);
  }, [sourcePreference, includeOwned, includePurchased, minScore, action, priority, limit]);

  // total reflects the post-filter count from the API - "no wishlist cards
  // at all" only applies when every filter is still at its default,
  // otherwise a total of 0 means the filters excluded everything.
  const filtersActive =
    includeOwned || includePurchased || minScore.trim() !== "" || action !== "all" || priority !== "all";
  const isEmptyWishlist =
    status === "ready" && data !== null && data.pagination.total === 0 && !filtersActive;
  const isEmptyForFilters =
    status === "ready" && data !== null && data.pagination.total === 0 && filtersActive;

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-1 flex items-baseline gap-3">
          <h1 className="text-lg font-semibold text-text-primary">Buy Decision Support</h1>
          <Link
            href="/wishlist"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Wishlist →
          </Link>
          <Link
            href="/analytics/wishlist"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Wishlist Analytics →
          </Link>
          <Link
            href="/market/opportunities"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Market Opportunities →
          </Link>
          <Link
            href="/analytics/digest"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Digest →
          </Link>
        </div>
        <p className="mb-1 text-sm text-text-muted">
          Review wishlist cards that may be worth buying, waiting on, skipping, or monitoring.
        </p>
        <p className="mb-4 text-xs text-text-faint">
          Signals are deterministic from your tracker data. Review manually before buying.
        </p>

        <div className="mb-6 flex flex-wrap items-end gap-4">
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-muted">
              Source preference
            </label>
            <div className="flex overflow-hidden rounded border border-border-default text-xs">
              {SOURCE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setSourcePreference(opt.value)}
                  className={`px-2.5 py-1 ${
                    sourcePreference === opt.value
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
              checked={includeOwned}
              onChange={(e) => setIncludeOwned(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-border-default bg-bg-surface"
            />
            Include owned
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

          <div>
            <label
              htmlFor="buy-decisions-min-score"
              className="mb-1 block text-[11px] uppercase tracking-wide text-text-muted"
            >
              Min score
            </label>
            <input
              id="buy-decisions-min-score"
              type="number"
              min={0}
              max={100}
              value={minScore}
              onChange={(e) => setMinScore(e.target.value)}
              placeholder="0"
              className="w-20 rounded border border-border-default bg-bg-surface px-2 py-1 text-xs text-text-primary"
            />
          </div>

          <div>
            <label
              htmlFor="buy-decisions-action"
              className="mb-1 block text-[11px] uppercase tracking-wide text-text-muted"
            >
              Action
            </label>
            <select
              id="buy-decisions-action"
              value={action}
              onChange={(e) => setAction(e.target.value as BuyDecisionAction | "all")}
              className="rounded border border-border-default bg-bg-surface px-2 py-1 text-xs text-text-primary"
            >
              {ACTION_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label
              htmlFor="buy-decisions-priority"
              className="mb-1 block text-[11px] uppercase tracking-wide text-text-muted"
            >
              Priority
            </label>
            <select
              id="buy-decisions-priority"
              value={priority}
              onChange={(e) => setPriority(e.target.value as BuyDecisionPriorityFilter | "all")}
              className="rounded border border-border-default bg-bg-surface px-2 py-1 text-xs text-text-primary"
            >
              {PRIORITY_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label
              htmlFor="buy-decisions-limit"
              className="mb-1 block text-[11px] uppercase tracking-wide text-text-muted"
            >
              Per page
            </label>
            <select
              id="buy-decisions-limit"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="rounded border border-border-default bg-bg-surface px-2 py-1 text-xs text-text-primary"
            >
              {LIMIT_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
        </div>

        {status === "loading" && <LoadingState>Loading buy decision support…</LoadingState>}
        {status === "unauthorized" && <ErrorState>Sign in to view buy decision support.</ErrorState>}
        {status === "error" && (
          <ErrorState>Failed to load buy decision support from the API.</ErrorState>
        )}

        {status === "ready" && data && isEmptyWishlist && (
          <EmptyState>No wishlist cards to analyze yet.</EmptyState>
        )}

        {status === "ready" && data && !isEmptyWishlist && (
          <>
            <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <StatCard label="Total candidates" value={formatNumber(data.summary.total_candidates)} />
              <StatCard
                label="Review buy"
                value={formatNumber(data.summary.review_buy_count)}
                tone={data.summary.review_buy_count > 0 ? "good" : undefined}
              />
              <StatCard label="Wait" value={formatNumber(data.summary.wait_count)} />
              <StatCard label="Skip" value={formatNumber(data.summary.skip_count)} />
              <StatCard
                label="Missing data"
                value={formatNumber(data.summary.missing_data_count)}
                tone={data.summary.missing_data_count > 0 ? "bad" : undefined}
              />
              <StatCard label="Monitor" value={formatNumber(data.summary.monitor_count)} />
              <StatCard
                label="Target hits"
                value={formatNumber(data.summary.target_hit_count)}
                tone={data.summary.target_hit_count > 0 ? "good" : undefined}
              />
              <StatCard
                label="Total target budget"
                value={formatJPY(data.summary.total_target_budget_jpy)}
              />
              <StatCard label="Current cost" value={formatJPY(data.summary.total_current_cost_jpy)} />
              <StatCard
                label="Budget gap"
                value={formatSignedJpy(data.summary.budget_gap_jpy)}
                tone={
                  data.summary.budget_gap_jpy > 0 ? "bad" : data.summary.budget_gap_jpy < 0 ? "good" : undefined
                }
              />
              <StatCard label="Average score" value={formatNumber(data.summary.average_score)} />
            </div>

            {isEmptyForFilters ? (
              <EmptyState>No buy decision candidates found for the selected filters.</EmptyState>
            ) : (
              <>
                <Section title="Recommended action groups">
                  <BuyDecisionActionGroups candidates={data.candidates} />
                </Section>

                <Section title="Candidates" last>
                  <BuyDecisionCandidateTable candidates={data.candidates} onCandidateUpdated={load} />
                  {/* Hand-rolled rather than the shared PaginationControls: this
                      API echoes authoritative next_offset/previous_offset/has_next/
                      has_previous (server-driven paging), which PaginationControls
                      doesn't use - it recomputes purely from client offset/limit/total. */}
                  <div className="mt-3 flex items-center justify-between text-xs text-text-muted">
                    <span>
                      Showing {data.candidates.length === 0 ? 0 : offset + 1}–
                      {offset + data.candidates.length} of {formatNumber(data.pagination.total)}
                    </span>
                    <div className="flex gap-2">
                      <ActionButton
                        onClick={() => setOffset(data.pagination.previous_offset ?? 0)}
                        disabled={!data.pagination.has_previous}
                      >
                        Previous
                      </ActionButton>
                      <ActionButton
                        onClick={() => setOffset(data.pagination.next_offset ?? offset)}
                        disabled={!data.pagination.has_next}
                      >
                        Next
                      </ActionButton>
                    </div>
                  </div>
                </Section>
              </>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function Section({
  title,
  children,
  last = false,
}: {
  title: string;
  children: React.ReactNode;
  last?: boolean;
}) {
  return (
    <section className={last ? "mb-2" : "mb-8"}>
      <h2 className="mb-2 text-sm font-semibold text-text-primary">{title}</h2>
      {children}
    </section>
  );
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: StatTone;
}) {
  return <SharedStatCard label={label} value={value} tone={tone} />;
}
