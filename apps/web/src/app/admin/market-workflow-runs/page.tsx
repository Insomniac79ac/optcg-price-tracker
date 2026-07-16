"use client";

import Link from "next/link";
import { Fragment, useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { MarketWorkflowRunStatusBadge } from "@/components/MarketWorkflowRunStatusBadge";
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

function naText(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return NA;
  return String(value);
}

export default function MarketWorkflowRunsPage() {
  const [runs, setRuns] = useState<MarketWorkflowRun[]>([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [status, setStatus] = useState<"loading" | "error" | "unauthorized" | "ready">(
    "loading",
  );
  const [expandedId, setExpandedId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    fetchMarketWorkflowRuns({ status: statusFilter || undefined, limit: 50 })
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
  }, [statusFilter]);

  const latest = runs.length > 0 ? runs[0] : null;

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-4 flex items-baseline justify-between">
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-semibold text-neutral-100">
              Market workflow runs
            </h1>
            <Link
              href="/admin/actions"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Admin actions
            </Link>
            <Link
              href="/admin/logs"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              App logs
            </Link>
          </div>
          <div className="flex items-center gap-3">
            {status === "ready" && (
              <span className="text-sm text-neutral-500">
                {total} run{total === 1 ? "" : "s"}
              </span>
            )}
            <AdminLogoutButton />
          </div>
        </div>

        {status === "unauthorized" && (
          <AdminAuthGate onTokenSaved={() => window.location.reload()} />
        )}

        {status === "loading" && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            Loading market workflow runs…
          </div>
        )}

        {status === "error" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Failed to load market workflow runs from the API. Is the backend running?
          </div>
        )}

        {status === "ready" && (
          <>
            <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <SummaryCard label="Latest run status">
                {latest ? (
                  <MarketWorkflowRunStatusBadge status={latest.status} />
                ) : (
                  <span className="text-sm text-neutral-500">{NA}</span>
                )}
              </SummaryCard>
              <SummaryCard label="Latest run time">
                <span className="text-sm font-medium text-neutral-100">
                  {latest ? formatDateTime(latest.started_at) : NA}
                </span>
              </SummaryCard>
              <SummaryCard label="Latest report ID">
                <span className="text-sm font-medium text-neutral-100">
                  {latest ? naText(latest.market_report_id) : NA}
                </span>
              </SummaryCard>
              <SummaryCard label="Latest Telegram digest status">
                <span className="text-sm font-medium text-neutral-100">
                  {latest ? naText(latest.telegram_digest_status) : NA}
                </span>
              </SummaryCard>
            </div>

            <div className="mb-4 flex gap-1">
              {STATUS_FILTERS.map((f) => (
                <button
                  key={f.value}
                  onClick={() => setStatusFilter(f.value)}
                  className={`rounded px-2.5 py-1 text-xs font-medium capitalize ring-1 ring-inset ${
                    statusFilter === f.value
                      ? "bg-neutral-100 text-neutral-900 ring-neutral-100"
                      : "bg-neutral-900 text-neutral-400 ring-neutral-800 hover:text-neutral-100"
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>

            {status === "ready" && runs.length === 0 && (
              <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
                No market workflow runs found.
              </div>
            )}

            {status === "ready" && runs.length > 0 && (
              <div className="overflow-x-auto rounded-lg border border-neutral-800">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                      <th className="px-2 py-1.5 font-medium">ID</th>
                      <th className="px-2 py-1.5 font-medium">Started</th>
                      <th className="px-2 py-1.5 font-medium">Finished</th>
                      <th className="px-2 py-1.5 font-medium">Status</th>
                      <th className="px-2 py-1.5 font-medium">Source</th>
                      <th className="px-2 py-1.5 font-medium">Limit</th>
                      <th className="px-2 py-1.5 font-medium">Telegram</th>
                      <th className="px-2 py-1.5 font-medium">Refresh run</th>
                      <th className="px-2 py-1.5 font-medium">Portfolio snapshot</th>
                      <th className="px-2 py-1.5 font-medium">Report</th>
                      <th className="px-2 py-1.5 font-medium">Signals c/u/r</th>
                      <th className="px-2 py-1.5 font-medium">Digest status</th>
                      <th className="px-2 py-1.5 font-medium">Warnings</th>
                      <th className="px-2 py-1.5 font-medium">Error</th>
                      <th className="px-2 py-1.5 font-medium">Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((run) => {
                      const isExpanded = expandedId === run.id;
                      return (
                        <Fragment key={run.id}>
                          <tr className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60">
                            <td className="px-2 py-1.5 font-mono text-neutral-400">{run.id}</td>
                            <td className="whitespace-nowrap px-2 py-1.5 text-neutral-400">
                              {formatDateTime(run.started_at)}
                            </td>
                            <td className="whitespace-nowrap px-2 py-1.5 text-neutral-400">
                              {formatDateTime(run.finished_at)}
                            </td>
                            <td className="px-2 py-1.5">
                              <MarketWorkflowRunStatusBadge status={run.status} />
                            </td>
                            <td className="px-2 py-1.5 text-neutral-300">{run.source}</td>
                            <td className="px-2 py-1.5 text-neutral-400">{naText(run.limit)}</td>
                            <td className="px-2 py-1.5 text-neutral-400">
                              {run.send_telegram ? "yes" : "no"}
                            </td>
                            <td className="px-2 py-1.5">
                              {run.price_refresh_run_id !== null ? (
                                <Link
                                  href="/admin/refresh-runs"
                                  className="text-sky-400 hover:text-sky-300"
                                >
                                  {run.price_refresh_run_id}
                                </Link>
                              ) : (
                                <span className="text-neutral-600">{NA}</span>
                              )}
                            </td>
                            <td className="px-2 py-1.5 text-neutral-400">
                              {naText(run.portfolio_snapshot_id)}
                            </td>
                            <td className="px-2 py-1.5">
                              {run.market_report_id !== null ? (
                                <Link
                                  href="/market/report"
                                  className="text-sky-400 hover:text-sky-300"
                                >
                                  {run.market_report_id}
                                </Link>
                              ) : (
                                <span className="text-neutral-600">{NA}</span>
                              )}
                            </td>
                            <td className="px-2 py-1.5 text-neutral-400">
                              {run.signal_events_created}/{run.signal_events_updated}/
                              {run.signal_events_resolved}
                            </td>
                            <td className="px-2 py-1.5 text-neutral-400">
                              {naText(run.telegram_digest_status)}
                            </td>
                            <td className="px-2 py-1.5">
                              <span
                                className={
                                  run.warnings.length > 0
                                    ? "font-semibold text-amber-300"
                                    : "text-neutral-400"
                                }
                              >
                                {run.warnings.length}
                              </span>
                            </td>
                            <td className="max-w-[12rem] px-2 py-1.5">
                              {run.error_message ? (
                                <span
                                  className="block truncate text-rose-300"
                                  title={run.error_message}
                                >
                                  {run.error_message}
                                </span>
                              ) : (
                                <span className="text-neutral-600">{NA}</span>
                              )}
                            </td>
                            <td className="px-2 py-1.5">
                              <button
                                onClick={() => setExpandedId(isExpanded ? null : run.id)}
                                className="text-xs font-medium text-neutral-400 hover:text-neutral-200"
                              >
                                {isExpanded ? "Hide" : "View"}
                              </button>
                            </td>
                          </tr>
                          {isExpanded && (
                            <tr className="border-b border-neutral-900 bg-neutral-950/60">
                              <td colSpan={15} className="px-4 py-3">
                                <div className="mb-2 text-[11px] uppercase tracking-wide text-neutral-500">
                                  Warnings
                                </div>
                                {run.warnings.length === 0 ? (
                                  <p className="mb-3 text-xs text-neutral-500">{NA}</p>
                                ) : (
                                  <ul className="mb-3 list-disc space-y-1 pl-6 text-xs text-amber-200">
                                    {run.warnings.map((w, i) => (
                                      <li key={i}>{w}</li>
                                    ))}
                                  </ul>
                                )}
                                <div className="mb-2 text-[11px] uppercase tracking-wide text-neutral-500">
                                  Error message
                                </div>
                                <p className="text-xs text-rose-300">
                                  {run.error_message ?? NA}
                                </p>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function SummaryCard({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="mb-1 text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      {children}
    </div>
  );
}
