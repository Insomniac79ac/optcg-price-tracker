"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { GradingAnalyticsBreakdownTable } from "@/components/GradingAnalyticsBreakdownTable";
import { GradingSubmissionTable } from "@/components/GradingSubmissionTable";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { AdminAuthRequiredError, fetchGradingAnalytics, type GradingAnalytics } from "@/lib/api";
import { formatJPY, formatNumber, formatPercent, formatSignedJpy } from "@/lib/format";

type PageStatus = "loading" | "unauthorized" | "error" | "ready";

const COMPANY_OPTIONS = ["PSA", "BGS", "CGC", "ARS", "Other"];
const STATUS_OPTIONS = [
  "planned",
  "preparing",
  "submitted",
  "grading",
  "shipped_back",
  "received",
  "cancelled",
];
const LIMIT_OPTIONS = [25, 50, 100, 200];

export default function GradingAnalyticsPage() {
  const [data, setData] = useState<GradingAnalytics | null>(null);
  const [status, setStatus] = useState<PageStatus>("loading");
  const [includeCancelled, setIncludeCancelled] = useState(false);
  const [gradingCompany, setGradingCompany] = useState<string>("");
  const [submissionStatus, setSubmissionStatus] = useState<string>("");
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);

  const load = useCallback(() => {
    setStatus("loading");
    fetchGradingAnalytics({
      include_cancelled: includeCancelled,
      grading_company: gradingCompany || undefined,
      status: submissionStatus || undefined,
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
  }, [includeCancelled, gradingCompany, submissionStatus, limit, offset]);

  useEffect(() => {
    load();
  }, [load]);

  // Any filter change other than pagination itself resets back to page 1.
  useEffect(() => {
    setOffset(0);
  }, [includeCancelled, gradingCompany, submissionStatus, limit]);

  const filtersActive = includeCancelled || gradingCompany !== "" || submissionStatus !== "";
  const isEmptyGrading =
    status === "ready" && data !== null && data.pagination.total === 0 && !filtersActive;
  const isEmptyForFilters =
    status === "ready" && data !== null && data.pagination.total === 0 && filtersActive;

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-1 flex items-baseline gap-3">
          <h1 className="text-lg font-semibold text-neutral-100">Grading ROI Analytics</h1>
          <Link
            href="/grading"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Grading →
          </Link>
          <Link
            href="/analytics/collection"
            className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
          >
            Collection Analytics →
          </Link>
        </div>
        <p className="mb-1 text-sm text-neutral-500">
          Costs, outcomes, pending submissions, and post-grade value.
        </p>
        <p className="mb-4 text-xs text-neutral-600">
          ROI is calculated from your entered cost basis, grading costs, and graded value.
        </p>

        <div className="mb-6 flex flex-wrap items-end gap-4">
          <label className="flex items-center gap-2 text-xs text-neutral-400">
            <input
              type="checkbox"
              checked={includeCancelled}
              onChange={(e) => setIncludeCancelled(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-neutral-700 bg-neutral-900"
            />
            Include cancelled
          </label>

          <div>
            <label
              htmlFor="grading-analytics-company"
              className="mb-1 block text-[11px] uppercase tracking-wide text-neutral-500"
            >
              Company
            </label>
            <select
              id="grading-analytics-company"
              value={gradingCompany}
              onChange={(e) => setGradingCompany(e.target.value)}
              className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
            >
              <option value="">All companies</option>
              {COMPANY_OPTIONS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label
              htmlFor="grading-analytics-status"
              className="mb-1 block text-[11px] uppercase tracking-wide text-neutral-500"
            >
              Status
            </label>
            <select
              id="grading-analytics-status"
              value={submissionStatus}
              onChange={(e) => setSubmissionStatus(e.target.value)}
              className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
            >
              <option value="">All statuses</option>
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s.replace("_", " ")}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label
              htmlFor="grading-analytics-limit"
              className="mb-1 block text-[11px] uppercase tracking-wide text-neutral-500"
            >
              Per page
            </label>
            <select
              id="grading-analytics-limit"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
            >
              {LIMIT_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
        </div>

        {status === "loading" && <LoadingState>Loading grading analytics…</LoadingState>}
        {status === "unauthorized" && <ErrorState>Sign in to view grading analytics.</ErrorState>}
        {status === "error" && <ErrorState>Failed to load grading analytics from the API.</ErrorState>}

        {status === "ready" && data && isEmptyGrading && (
          <EmptyState>No grading submissions to analyze yet.</EmptyState>
        )}

        {status === "ready" && data && !isEmptyGrading && (
          <>
            <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7">
              <StatCard label="Total submissions" value={formatNumber(data.summary.total_submissions)} />
              <StatCard label="Active" value={formatNumber(data.summary.active_submissions)} />
              <StatCard label="Received" value={formatNumber(data.summary.received_submissions)} />
              <StatCard
                label="Total declared value"
                value={formatJPY(data.summary.total_declared_value_jpy)}
              />
              <StatCard label="Total grading cost" value={formatJPY(data.summary.total_grading_cost_jpy)} />
              <StatCard label="Total graded value" value={formatJPY(data.summary.total_graded_value_jpy)} />
              <StatCard
                label="Total ROI"
                value={formatSignedJpy(data.summary.total_roi_jpy)}
                tone={
                  data.summary.total_roi_jpy > 0 ? "good" : data.summary.total_roi_jpy < 0 ? "bad" : undefined
                }
              />
              <StatCard label="ROI %" value={formatPercent(data.summary.total_roi_pct)} />
              <StatCard
                label="Average grade"
                value={data.summary.average_grade === null ? "not available" : formatNumber(data.summary.average_grade)}
              />
              <StatCard
                label="Median grade"
                value={data.summary.median_grade === null ? "not available" : formatNumber(data.summary.median_grade)}
              />
              <StatCard
                label="Profitable"
                value={formatNumber(data.summary.profitable_count)}
                tone={data.summary.profitable_count > 0 ? "good" : undefined}
              />
              <StatCard label="Unprofitable" value={formatNumber(data.summary.unprofitable_count)} />
              <StatCard
                label="Missing graded value"
                value={formatNumber(data.summary.missing_graded_value_count)}
                tone={data.summary.missing_graded_value_count > 0 ? "bad" : undefined}
              />
              <StatCard label="Waiting return" value={formatNumber(data.summary.items_waiting_return)} />
            </div>

            {isEmptyForFilters ? (
              <EmptyState>No grading submissions found for the selected filters.</EmptyState>
            ) : (
              <>
                <Section title="ROI">
                  <SubSection title="Best ROI submissions">
                    <GradingSubmissionTable
                      submissions={data.roi.best_roi_submissions}
                      columns={["company", "final_grade", "total_cost", "raw_cost_basis", "graded_value", "roi", "roi_pct"]}
                    />
                  </SubSection>
                  <SubSection title="Worst ROI submissions">
                    <GradingSubmissionTable
                      submissions={data.roi.worst_roi_submissions}
                      columns={["company", "final_grade", "total_cost", "raw_cost_basis", "graded_value", "roi", "roi_pct"]}
                    />
                  </SubSection>
                  <SubSection title="Highest graded value">
                    <GradingSubmissionTable
                      submissions={data.roi.highest_graded_value}
                      columns={["company", "final_grade", "total_cost", "raw_cost_basis", "graded_value", "roi", "roi_pct"]}
                    />
                  </SubSection>
                  <SubSection title="Highest grading cost">
                    <GradingSubmissionTable
                      submissions={data.roi.highest_grading_cost}
                      columns={["company", "final_grade", "total_cost", "raw_cost_basis", "graded_value", "roi", "roi_pct"]}
                    />
                  </SubSection>
                  <SubSection title="Missing value or cost" last>
                    <GradingSubmissionTable
                      submissions={data.roi.missing_value_or_cost}
                      columns={["company", "final_grade", "total_cost", "raw_cost_basis", "graded_value", "roi", "roi_pct"]}
                    />
                  </SubSection>
                </Section>

                <Section title="Pending">
                  <SubSection title="Waiting return">
                    <GradingSubmissionTable
                      submissions={data.pending.waiting_return}
                      columns={["company", "status", "submitted_at", "expected_return_date", "days_in_grading", "tracking_number"]}
                    />
                  </SubSection>
                  <SubSection title="Overdue">
                    <GradingSubmissionTable
                      submissions={data.pending.overdue}
                      columns={["company", "status", "submitted_at", "expected_return_date", "days_in_grading", "tracking_number"]}
                    />
                  </SubSection>
                  <SubSection title="Expected next 30 days" last>
                    <GradingSubmissionTable
                      submissions={data.pending.expected_next_30d}
                      columns={["company", "status", "submitted_at", "expected_return_date", "days_in_grading", "tracking_number"]}
                    />
                  </SubSection>
                </Section>

                <Section title="By status">
                  <GradingAnalyticsBreakdownTable
                    rows={data.breakdowns.by_status}
                    firstColumnLabel="Status"
                    columns={["submission_count", "received_count", "active_count", "total_cost_jpy", "graded_value_jpy", "roi_jpy", "roi_pct"]}
                  />
                </Section>

                <Section title="By company">
                  <GradingAnalyticsBreakdownTable
                    rows={data.breakdowns.by_company}
                    firstColumnLabel="Company"
                    columns={["submission_count", "received_count", "active_count", "total_cost_jpy", "graded_value_jpy", "roi_jpy", "roi_pct"]}
                  />
                </Section>

                <Section title="By grade">
                  <GradingAnalyticsBreakdownTable
                    rows={data.breakdowns.by_grade}
                    firstColumnLabel="Grade"
                    columns={["submission_count", "total_cost_jpy", "graded_value_jpy", "roi_jpy", "roi_pct"]}
                  />
                </Section>

                <Section title="By set">
                  <GradingAnalyticsBreakdownTable
                    rows={data.breakdowns.by_set}
                    firstColumnLabel="Set"
                    columns={["submission_count", "total_cost_jpy", "graded_value_jpy", "roi_jpy", "roi_pct"]}
                  />
                </Section>

                <Section title="By rarity">
                  <GradingAnalyticsBreakdownTable
                    rows={data.breakdowns.by_rarity}
                    firstColumnLabel="Rarity"
                    columns={["submission_count", "total_cost_jpy", "graded_value_jpy", "roi_jpy", "roi_pct"]}
                  />
                </Section>

                <Section title="Submissions" last>
                  <GradingSubmissionTable
                    submissions={data.submissions}
                    columns={["company", "status", "final_grade", "total_cost", "raw_cost_basis", "graded_value", "roi", "submitted_at", "expected_return_date", "received_at", "overdue", "notes"]}
                    actions
                    onSubmissionUpdated={load}
                  />
                  <div className="mt-3 flex items-center justify-between text-xs text-neutral-500">
                    <span>
                      Showing {data.submissions.length === 0 ? 0 : offset + 1}–
                      {offset + data.submissions.length} of {formatNumber(data.pagination.total)}
                    </span>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => setOffset(data.pagination.previous_offset ?? 0)}
                        disabled={!data.pagination.has_previous}
                        className="rounded border border-neutral-700 px-2.5 py-1 text-neutral-300 hover:text-neutral-100 disabled:opacity-40"
                      >
                        Previous
                      </button>
                      <button
                        type="button"
                        onClick={() => setOffset(data.pagination.next_offset ?? offset)}
                        disabled={!data.pagination.has_next}
                        className="rounded border border-neutral-700 px-2.5 py-1 text-neutral-300 hover:text-neutral-100 disabled:opacity-40"
                      >
                        Next
                      </button>
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
      <h2 className="mb-2 text-sm font-semibold text-neutral-200">{title}</h2>
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
  children: React.ReactNode;
  last?: boolean;
}) {
  return (
    <div className={last ? "mb-0" : "mb-4"}>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">{title}</h3>
      {children}
    </div>
  );
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "good" | "bad";
}) {
  const toneClass = tone === "good" ? "text-emerald-400" : tone === "bad" ? "text-amber-400" : "text-neutral-100";
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}
