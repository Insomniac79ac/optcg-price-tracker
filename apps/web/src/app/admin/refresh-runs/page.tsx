"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { RunStatusBadge } from "@/components/RunStatusBadge";
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

export default function RefreshRunsPage() {
  const [runs, setRuns] = useState<PriceRefreshRun[]>([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [status, setStatus] = useState<
    "loading" | "error" | "unauthorized" | "ready"
  >("loading");

  useEffect(() => {
    let cancelled = false;

    fetchRefreshRuns({ status: statusFilter || undefined, limit: 100 })
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

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-4 flex items-baseline justify-between">
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-semibold text-neutral-100">
              Price refresh runs
            </h1>
            <Link
              href="/admin/actions"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Admin actions
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

        <div className="mb-4 flex gap-1">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => setStatusFilter(f.value)}
              className={`rounded px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                statusFilter === f.value
                  ? "bg-neutral-100 text-neutral-900 ring-neutral-100"
                  : "bg-neutral-900 text-neutral-400 ring-neutral-800 hover:text-neutral-100"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        {status === "unauthorized" && (
          <AdminAuthGate onTokenSaved={() => window.location.reload()} />
        )}

        {status === "loading" && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            Loading refresh runs…
          </div>
        )}

        {status === "error" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Failed to load refresh runs from the API. Is the backend running?
          </div>
        )}

        {status === "ready" && runs.length === 0 && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            No refresh runs found.
          </div>
        )}

        {status === "ready" && runs.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-neutral-800">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wide text-neutral-500">
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Mode</th>
                  <th className="px-3 py-2 font-medium">Source</th>
                  <th className="px-3 py-2 font-medium">Started</th>
                  <th className="px-3 py-2 font-medium">Finished</th>
                  <th className="px-3 py-2 font-medium text-right">
                    Checked
                  </th>
                  <th className="px-3 py-2 font-medium text-right">
                    Inserted
                  </th>
                  <th className="px-3 py-2 font-medium text-right">Failed</th>
                  <th className="px-3 py-2 font-medium">Error</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr
                    key={run.id}
                    className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                  >
                    <td className="px-3 py-2">
                      <RunStatusBadge status={run.status} />
                    </td>
                    <td className="px-3 py-2 text-neutral-300">
                      {run.scraping_mode}
                      {run.dry_run && (
                        <span className="ml-1 text-xs text-neutral-500">
                          (dry-run)
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-neutral-400">
                      {run.source_filter ?? "all"}
                    </td>
                    <td className="px-3 py-2 text-xs text-neutral-500">
                      {formatDateTime(run.started_at)}
                    </td>
                    <td className="px-3 py-2 text-xs text-neutral-500">
                      {formatDateTime(run.finished_at)}
                    </td>
                    <td className="px-3 py-2 text-right text-neutral-300">
                      {run.mappings_checked}
                    </td>
                    <td className="px-3 py-2 text-right text-neutral-300">
                      {run.observations_inserted}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span
                        className={
                          run.mappings_failed > 0
                            ? "font-medium text-rose-400"
                            : "text-neutral-400"
                        }
                      >
                        {run.mappings_failed}
                      </span>
                    </td>
                    <td className="max-w-xs px-3 py-2">
                      {run.error_message ? (
                        <span
                          className="block truncate text-xs text-rose-300"
                          title={run.error_message}
                        >
                          {run.error_message}
                        </span>
                      ) : (
                        <span className="text-neutral-600">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}
