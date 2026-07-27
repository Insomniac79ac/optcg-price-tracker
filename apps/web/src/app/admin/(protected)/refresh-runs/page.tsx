"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminSessionExpired } from "@/components/AdminSessionExpired";
import { AppHeader } from "@/components/AppHeader";
import { PaginationControls } from "@/components/PaginationControls";
import { RunStatusBadge } from "@/components/RunStatusBadge";
import { ErrorState, LoadingState } from "@/components/StateBlocks";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  AdminAuthRequiredError,
  type PriceRefreshRun,
  fetchRefreshRuns,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "running", label: "Running" },
  { value: "completed", label: "Completed" },
  { value: "completed_with_warnings", label: "Warnings" },
  { value: "failed", label: "Failed" },
];

const LIMIT_OPTIONS = [25, 50, 100, 200] as const;

export default function RefreshRunsPage() {
  const [runs, setRuns] = useState<PriceRefreshRun[]>([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState<
    "loading" | "error" | "unauthorized" | "ready"
  >("loading");

  // A filter change re-pages to the start - an offset from the old filter's
  // result set is otherwise almost certainly out of range for the new one.
  useEffect(() => {
    setOffset(0);
  }, [statusFilter, limit]);

  useEffect(() => {
    let cancelled = false;

    fetchRefreshRuns({ status: statusFilter || undefined, limit, offset })
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

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <PageHeader
          title="Price refresh runs"
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
          <Link href="/admin/market-workflow-runs" className="text-sky-400 hover:underline">
            Market workflow runs
          </Link>
          <Link href="/admin/price-source-health" className="text-sky-400 hover:underline">
            Price source health
          </Link>
        </div>

        <div className="mb-4 flex gap-1">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setStatusFilter(f.value)}
              className={`rounded-control px-2.5 py-1 text-xs font-medium ring-1 ring-inset transition-colors ${
                statusFilter === f.value
                  ? "bg-accent-gold text-black/80 ring-accent-gold"
                  : "bg-bg-surface text-text-secondary ring-border-default hover:text-text-primary"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        {status === "unauthorized" && (
          <AdminSessionExpired />
        )}

        {status === "loading" && <LoadingState>Loading refresh runs…</LoadingState>}

        {status === "error" && (
          <ErrorState>Failed to load refresh runs from the API. Is the backend running?</ErrorState>
        )}

        {status === "ready" && (
          <DataTableShell isEmpty={runs.length === 0} emptyLabel="No refresh runs found.">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Mode</th>
                  <th>Source</th>
                  <th>Started</th>
                  <th>Finished</th>
                  <th className="text-right">Checked</th>
                  <th className="text-right">Inserted</th>
                  <th className="text-right">Failed</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <RunStatusBadge status={run.status} />
                    </td>
                    <td className="text-text-secondary">
                      {run.scraping_mode}
                      {run.dry_run && <span className="ml-1 text-xs text-text-muted">(dry-run)</span>}
                    </td>
                    <td className="text-text-secondary">{run.source_filter ?? "all"}</td>
                    <td className="mono text-xs text-text-muted">{formatDateTime(run.started_at)}</td>
                    <td className="mono text-xs text-text-muted">{formatDateTime(run.finished_at)}</td>
                    <td className="mono tabular text-right text-text-secondary">{run.mappings_checked}</td>
                    <td className="mono tabular text-right text-text-secondary">
                      {run.observations_inserted}
                    </td>
                    <td className="mono tabular text-right">
                      <span className={run.mappings_failed > 0 ? "font-medium text-signal-red" : "text-text-secondary"}>
                        {run.mappings_failed}
                      </span>
                    </td>
                    <td className="max-w-xs">
                      {run.error_message ? (
                        <span className="block truncate text-xs text-signal-red" title={run.error_message}>
                          {run.error_message}
                        </span>
                      ) : (
                        <span className="text-text-faint">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DataTableShell>
        )}

        {status === "ready" && (
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
        )}
      </main>
    </div>
  );
}
