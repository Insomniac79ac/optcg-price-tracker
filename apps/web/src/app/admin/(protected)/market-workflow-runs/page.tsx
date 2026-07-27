"use client";

import Link from "next/link";
import { Fragment, useEffect, useState } from "react";

import { AdminSessionExpired } from "@/components/AdminSessionExpired";
import { AppHeader } from "@/components/AppHeader";
import { MarketWorkflowRunStatusBadge } from "@/components/MarketWorkflowRunStatusBadge";
import { PaginationControls } from "@/components/PaginationControls";
import { ErrorState, LoadingState } from "@/components/StateBlocks";
import { ActionButton } from "@/components/ui/ActionButton";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatCard, StatGrid } from "@/components/ui/StatCard";
import {
  AdminAuthRequiredError,
  MARKET_WORKFLOW_RUN_STATUSES,
  type MarketWorkflowRun,
  fetchMarketWorkflowRuns,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";

const NA = "not available";

const ALL_OPTION = { value: "", label: "All" };
const STATUS_FILTERS = [
  ALL_OPTION,
  ...MARKET_WORKFLOW_RUN_STATUSES.map((s) => ({ value: s, label: s.replace("_", " ") })),
];

const LIMIT_OPTIONS = [25, 50, 100, 200] as const;

function naText(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return NA;
  return String(value);
}

export default function MarketWorkflowRunsPage() {
  const [runs, setRuns] = useState<MarketWorkflowRun[]>([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [limit, setLimit] = useState(50);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState<"loading" | "error" | "unauthorized" | "ready">(
    "loading",
  );
  const [expandedId, setExpandedId] = useState<number | null>(null);

  // A filter change re-pages to the start - an offset from the old filter's
  // result set is otherwise almost certainly out of range for the new one.
  useEffect(() => {
    setOffset(0);
  }, [statusFilter, limit]);

  useEffect(() => {
    let cancelled = false;

    fetchMarketWorkflowRuns({ status: statusFilter || undefined, limit, offset })
      .then((data) => {
        if (cancelled) return;
        setRuns(data.items);
        setTotal(data.total);
        setStatus("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        setStatus(err instanceof AdminAuthRequiredError ? "unauthorized" : "error");
      });

    return () => {
      cancelled = true;
    };
  }, [statusFilter, limit, offset]);

  // Only meaningful on the first page (runs are newest-first) - on later
  // pages runs[0] is just the newest item of that page, not the true latest
  // run, so the summary cards fall back to "not available" rather than
  // showing something misleading.
  const latest = offset === 0 && runs.length > 0 ? runs[0] : null;

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <PageHeader
          title="Market workflow runs"
          actions={
            <>
              {status === "ready" && (
                <span className="text-sm text-text-muted">
                  {total} run{total === 1 ? "" : "s"}
                </span>
              )}
            </>
          }
        />
        <div className="mb-4 flex flex-wrap gap-3 text-xs text-text-muted">
          <Link href="/admin/actions" className="text-sky-400 hover:underline">
            Admin actions
          </Link>
          <Link href="/admin/logs" className="text-sky-400 hover:underline">
            App logs
          </Link>
        </div>

        {status === "unauthorized" && (
          <AdminSessionExpired />
        )}

        {status === "loading" && <LoadingState>Loading market workflow runs…</LoadingState>}

        {status === "error" && (
          <ErrorState>Failed to load market workflow runs from the API. Is the backend running?</ErrorState>
        )}

        {status === "ready" && (
          <>
            <StatGrid>
              <StatCard
                label="Latest run status"
                value={latest ? <MarketWorkflowRunStatusBadge status={latest.status} /> : NA}
              />
              <StatCard label="Latest run time" value={latest ? formatDateTime(latest.started_at) : NA} />
              <StatCard label="Latest report ID" value={latest ? naText(latest.market_report_id) : NA} />
              <StatCard
                label="Latest Telegram digest status"
                value={latest ? naText(latest.telegram_digest_status) : NA}
              />
            </StatGrid>

            <div className="mb-4 mt-4 flex gap-1">
              {STATUS_FILTERS.map((f) => (
                <button
                  key={f.value}
                  type="button"
                  onClick={() => setStatusFilter(f.value)}
                  className={`rounded-control px-2.5 py-1 text-xs font-medium capitalize ring-1 ring-inset transition-colors ${
                    statusFilter === f.value
                      ? "bg-accent-gold text-black/80 ring-accent-gold"
                      : "bg-bg-surface text-text-secondary ring-border-default hover:text-text-primary"
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>

            <DataTableShell isEmpty={runs.length === 0} emptyLabel="No market workflow runs found." minWidth={1400}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Started</th>
                    <th>Finished</th>
                    <th>Status</th>
                    <th>Source</th>
                    <th>Limit</th>
                    <th>Telegram</th>
                    <th>Refresh run</th>
                    <th>Portfolio snapshot</th>
                    <th>Report</th>
                    <th>Signals c/u/r</th>
                    <th>Digest status</th>
                    <th>Warnings</th>
                    <th>Error</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => {
                    const isExpanded = expandedId === run.id;
                    return (
                      <Fragment key={run.id}>
                        <tr>
                          <td className="mono text-text-secondary">{run.id}</td>
                          <td className="mono whitespace-nowrap text-text-secondary">
                            {formatDateTime(run.started_at)}
                          </td>
                          <td className="mono whitespace-nowrap text-text-secondary">
                            {formatDateTime(run.finished_at)}
                          </td>
                          <td>
                            <MarketWorkflowRunStatusBadge status={run.status} />
                          </td>
                          <td className="text-text-secondary">{run.source}</td>
                          <td className="text-text-secondary">{naText(run.limit)}</td>
                          <td className="text-text-secondary">{run.send_telegram ? "yes" : "no"}</td>
                          <td>
                            {run.price_refresh_run_id !== null ? (
                              <Link href="/admin/refresh-runs" className="text-sky-400 hover:underline">
                                {run.price_refresh_run_id}
                              </Link>
                            ) : (
                              <span className="text-text-faint">{NA}</span>
                            )}
                          </td>
                          <td className="text-text-secondary">{naText(run.portfolio_snapshot_id)}</td>
                          <td>
                            {run.market_report_id !== null ? (
                              <Link href="/market/report" className="text-sky-400 hover:underline">
                                {run.market_report_id}
                              </Link>
                            ) : (
                              <span className="text-text-faint">{NA}</span>
                            )}
                          </td>
                          <td className="text-text-secondary">
                            {run.signal_events_created}/{run.signal_events_updated}/
                            {run.signal_events_resolved}
                          </td>
                          <td className="text-text-secondary">{naText(run.telegram_digest_status)}</td>
                          <td>
                            <span className={run.warnings.length > 0 ? "font-semibold text-signal-warning" : "text-text-secondary"}>
                              {run.warnings.length}
                            </span>
                          </td>
                          <td className="max-w-[12rem]">
                            {run.error_message ? (
                              <span className="block truncate text-signal-red" title={run.error_message}>
                                {run.error_message}
                              </span>
                            ) : (
                              <span className="text-text-faint">{NA}</span>
                            )}
                          </td>
                          <td>
                            <ActionButton onClick={() => setExpandedId(isExpanded ? null : run.id)}>
                              {isExpanded ? "Hide" : "View"}
                            </ActionButton>
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr>
                            <td colSpan={15} className="bg-bg-page/60">
                              <div className="mb-2 text-[11px] uppercase tracking-wide text-text-muted">
                                Warnings
                              </div>
                              {run.warnings.length === 0 ? (
                                <p className="mb-3 text-xs text-text-muted">{NA}</p>
                              ) : (
                                <ul className="mb-3 list-disc space-y-1 pl-6 text-xs text-signal-warning">
                                  {run.warnings.map((w, i) => (
                                    <li key={i}>{w}</li>
                                  ))}
                                </ul>
                              )}
                              <div className="mb-2 text-[11px] uppercase tracking-wide text-text-muted">
                                Error message
                              </div>
                              <p className="text-xs text-signal-red">{run.error_message ?? NA}</p>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </DataTableShell>

            <div className="mt-3">
              <PaginationControls
                offset={offset}
                limit={limit}
                total={total}
                onOffsetChange={setOffset}
                limitOptions={LIMIT_OPTIONS}
                onLimitChange={setLimit}
              />
            </div>
          </>
        )}
      </main>
    </div>
  );
}
