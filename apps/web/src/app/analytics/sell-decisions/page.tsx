"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { SellDecisionActionGroups } from "@/components/SellDecisionActionGroups";
import { SellDecisionCandidateTable } from "@/components/SellDecisionCandidateTable";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { ActionButton } from "@/components/ui/ActionButton";
import { SavedViewBar } from "@/components/ui/SavedViewBar";
import { StatCard as SharedStatCard, type StatTone } from "@/components/ui/StatCard";
import {
  AdminAuthRequiredError,
  fetchSellDecisions,
  type SellDecisionAction,
  type SellDecisionSupport,
} from "@/lib/api";
import { formatJPY, formatNumber, formatSignedJpy } from "@/lib/format";

type PageStatus = "loading" | "unauthorized" | "error" | "ready";
type ValuationMode = "raw_market" | "graded_adjusted";

const ACTION_OPTIONS: { value: SellDecisionAction | "all"; label: string }[] = [
  { value: "all", label: "All actions" },
  { value: "review_sell", label: "Review sell" },
  { value: "hold", label: "Hold" },
  { value: "grade_first", label: "Grade first" },
  { value: "missing_data", label: "Missing data" },
  { value: "monitor", label: "Monitor" },
];

const LIMIT_OPTIONS = [25, 50, 100, 200];

export default function SellDecisionsPage() {
  const [data, setData] = useState<SellDecisionSupport | null>(null);
  const [status, setStatus] = useState<PageStatus>("loading");
  const [valuationMode, setValuationMode] = useState<ValuationMode>("raw_market");
  const [includeSold, setIncludeSold] = useState(false);
  const [minScore, setMinScore] = useState<string>("");
  const [action, setAction] = useState<SellDecisionAction | "all">("all");
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);

  const load = useCallback(() => {
    setStatus("loading");
    fetchSellDecisions({
      valuation_mode: valuationMode,
      include_sold: includeSold,
      min_score: minScore.trim() === "" ? undefined : Number(minScore),
      action: action === "all" ? undefined : action,
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
  }, [valuationMode, includeSold, minScore, action, limit, offset]);

  useEffect(() => {
    load();
  }, [load]);

  // Any filter change other than pagination itself resets back to page 1.
  useEffect(() => {
    setOffset(0);
  }, [valuationMode, includeSold, minScore, action, limit]);

  // total reflects the post-filter count from the API - "no owned cards at
  // all" only applies when every filter is still at its default, otherwise
  // a total of 0 means the filters excluded everything, not an empty
  // collection.
  const filtersActive = includeSold || minScore.trim() !== "" || action !== "all";
  const isEmptyCollection =
    status === "ready" && data !== null && data.pagination.total === 0 && !filtersActive;
  const isEmptyForFilters =
    status === "ready" && data !== null && data.pagination.total === 0 && filtersActive;

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-1 flex items-baseline gap-3">
          <h1 className="text-lg font-semibold text-text-primary">Sell Decision Support</h1>
          <Link
            href="/collection"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Collection →
          </Link>
          <Link
            href="/analytics/collection"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Collection Analytics →
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
          Review owned cards that may be worth selling, holding, grading first, or monitoring.
        </p>
        <p className="mb-4 text-xs text-text-faint">
          This is decision support, not financial advice. Signals are deterministic from your tracker
          data. Review manually before selling.
        </p>

        <div className="mb-6 flex flex-wrap items-end gap-4">
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-wide text-text-muted">
              Valuation mode
            </label>
            <div className="flex overflow-hidden rounded border border-border-default text-xs">
              {(["raw_market", "graded_adjusted"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setValuationMode(mode)}
                  className={`px-2.5 py-1 ${
                    valuationMode === mode
                      ? "bg-sky-500/20 text-sky-300"
                      : "bg-bg-surface text-text-secondary hover:text-text-primary"
                  }`}
                >
                  {mode === "raw_market" ? "Raw market" : "Graded adjusted"}
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
            Include sold
          </label>

          <div>
            <label
              htmlFor="sell-decisions-min-score"
              className="mb-1 block text-[11px] uppercase tracking-wide text-text-muted"
            >
              Min score
            </label>
            <input
              id="sell-decisions-min-score"
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
              htmlFor="sell-decisions-action"
              className="mb-1 block text-[11px] uppercase tracking-wide text-text-muted"
            >
              Action
            </label>
            <select
              id="sell-decisions-action"
              value={action}
              onChange={(e) => setAction(e.target.value as SellDecisionAction | "all")}
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
              htmlFor="sell-decisions-limit"
              className="mb-1 block text-[11px] uppercase tracking-wide text-text-muted"
            >
              Per page
            </label>
            <select
              id="sell-decisions-limit"
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

        <SavedViewBar
          routePath="/analytics/sell-decisions"
          viewType="sell_decisions"
          scope="analytics"
          currentFilters={{
            valuationMode,
            includeSold,
            minScore: minScore.trim() === "" ? undefined : Number(minScore),
            action,
          }}
          onApply={(filters) => {
            if (typeof filters.valuationMode === "string")
              setValuationMode(filters.valuationMode as ValuationMode);
            if (typeof filters.includeSold === "boolean") setIncludeSold(filters.includeSold);
            if (typeof filters.minScore === "number") setMinScore(String(filters.minScore));
            else if (filters.minScore === undefined) setMinScore("");
            if (typeof filters.action === "string")
              setAction(filters.action as SellDecisionAction | "all");
            setOffset(0);
          }}
        />

        {status === "loading" && <LoadingState>Loading sell decision support…</LoadingState>}
        {status === "unauthorized" && (
          <ErrorState>Sign in to view sell decision support.</ErrorState>
        )}
        {status === "error" && (
          <ErrorState>Failed to load sell decision support from the API.</ErrorState>
        )}

        {status === "ready" && data && isEmptyCollection && (
          <EmptyState>No owned cards to analyze yet.</EmptyState>
        )}

        {status === "ready" && data && !isEmptyCollection && (
          <>
            <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <StatCard label="Total candidates" value={formatNumber(data.summary.total_candidates)} />
              <StatCard
                label="Review sell"
                value={formatNumber(data.summary.review_sell_count)}
                tone={data.summary.review_sell_count > 0 ? "good" : undefined}
              />
              <StatCard label="Hold" value={formatNumber(data.summary.hold_count)} />
              <StatCard label="Grade first" value={formatNumber(data.summary.grade_first_count)} />
              <StatCard
                label="Missing data"
                value={formatNumber(data.summary.missing_data_count)}
                tone={data.summary.missing_data_count > 0 ? "bad" : undefined}
              />
              <StatCard label="Monitor" value={formatNumber(data.summary.monitor_count)} />
              <StatCard
                label="Potential sale value"
                value={formatJPY(data.summary.total_potential_sale_value_jpy)}
              />
              <StatCard
                label="Unrealized P/L"
                value={formatSignedJpy(data.summary.total_unrealized_pnl_jpy)}
                tone={
                  data.summary.total_unrealized_pnl_jpy > 0
                    ? "good"
                    : data.summary.total_unrealized_pnl_jpy < 0
                      ? "bad"
                      : undefined
                }
              />
              <StatCard label="Average score" value={formatNumber(data.summary.average_score)} />
            </div>

            {isEmptyForFilters ? (
              <EmptyState>No sell decision candidates found for the selected filters.</EmptyState>
            ) : (
              <>
                <Section title="Recommended action groups">
                  <SellDecisionActionGroups candidates={data.candidates} />
                </Section>

                <Section title="Candidates" last>
                  <SellDecisionCandidateTable candidates={data.candidates} onCandidateUpdated={load} />
                  {/* Hand-rolled rather than the shared PaginationControls: this
                      API echoes authoritative next_offset/previous_offset/has_next/
                      has_previous (server-driven paging), which PaginationControls
                      doesn't use - it recomputes purely from client offset/limit/total. */}
                  <div className="mt-3 flex items-center justify-between text-xs text-text-muted">
                    <span>
                      Showing {data.candidates.length === 0 ? 0 : offset + 1}–{offset + data.candidates.length} of{" "}
                      {formatNumber(data.pagination.total)}
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
