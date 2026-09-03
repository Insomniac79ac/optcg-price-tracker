"use client";

import { useEffect, useState } from "react";

import { AdminSessionExpired } from "@/components/AdminSessionExpired";
import { AppHeader } from "@/components/AppHeader";
import { PaginationControls } from "@/components/PaginationControls";
import { ErrorState, LoadingState } from "@/components/StateBlocks";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  AdminAuthRequiredError,
  type CollectionAttempt,
  type CollectionAttemptSummary,
  fetchCollectionAttempts,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";

/**
 * Read-only view over source_collection_attempts.
 *
 * The table exists because collector failures used to leave nothing behind:
 * on 2026-09-02 the first full 214-mapping run had three failures and one of
 * them is permanently unexplainable, because Railway dropped its log lines and
 * no row was written anywhere. This page is how the durable replacement gets
 * read. It is deliberately an inspection surface and nothing more - no retry,
 * no manual run, no edit.
 */

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "written", label: "Written" },
  { value: "validation_failed", label: "Validation" },
  { value: "no_extraction_attempted", label: "No extraction" },
  { value: "operational_error", label: "Operational" },
  { value: "mapping_load_failed", label: "Load failed" },
  { value: "skipped", label: "Skipped" },
  { value: "selected", label: "Unfinished" },
];

const STAGE_FILTERS = [
  { value: "", label: "Any stage" },
  { value: "load", label: "load" },
  { value: "browser_launch", label: "browser_launch" },
  { value: "homepage", label: "homepage" },
  { value: "product", label: "product" },
  { value: "extraction", label: "extraction" },
  { value: "validation", label: "validation" },
  { value: "write", label: "write" },
];

const LIMIT_OPTIONS = [25, 50, 100, 200] as const;

// 'written' is the only outcome that is not a problem; 'selected' is not an
// outcome at all. Everything else is worth the eye going to it first.
function statusTone(status: string): string {
  if (status === "written") return "text-emerald-400";
  if (status === "selected") return "text-text-muted";
  if (status === "skipped") return "text-amber-400";
  return "text-red-400";
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds % 60)}s`;
}

function BatchSummary({
  summary,
  batchRunId,
}: {
  summary: CollectionAttemptSummary;
  batchRunId: string;
}) {
  const stages = Object.entries(summary.by_failure_stage);
  return (
    <div className="panel mb-4 p-4">
      <div className="mb-3 flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-text-primary">
          {batchRunId ? "Batch summary" : "Summary (all attempts)"}
        </h2>
        {batchRunId && <code className="mono text-xs text-text-muted">{batchRunId}</code>}
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3 lg:grid-cols-6">
        {[
          ["Selected", summary.total_attempts],
          ["Started", summary.started],
          ["Written", summary.written],
          ["Skipped", summary.skipped],
          ["Denied", summary.source_denied],
          ["Unfinished", summary.still_selected],
        ].map(([label, value]) => (
          <div key={String(label)}>
            <dt className="text-xs text-text-muted">{label}</dt>
            <dd className="mono text-text-primary">{value}</dd>
          </div>
        ))}
      </dl>
      {stages.length > 0 && (
        <p className="mt-3 text-xs text-text-secondary">
          Failure stages:{" "}
          {stages.map(([stage, count], i) => (
            <span key={stage}>
              {i > 0 && ", "}
              <code className="mono">{stage}</code> ×{count}
            </span>
          ))}
        </p>
      )}
      <p className="mt-2 text-xs text-text-muted">
        {summary.earliest_selected_at
          ? `Selected ${formatDateTime(summary.earliest_selected_at)}`
          : "Selected —"}
        {" · "}
        {summary.latest_finished_at
          ? `last finished ${formatDateTime(summary.latest_finished_at)}`
          : "none finished"}
      </p>
    </div>
  );
}

export default function CollectionAttemptsPage() {
  const [attempts, setAttempts] = useState<CollectionAttempt[]>([]);
  const [summary, setSummary] = useState<CollectionAttemptSummary | null>(null);
  const [total, setTotal] = useState(0);
  const [batchRunId, setBatchRunId] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [stageFilter, setStageFilter] = useState("");
  const [deniedOnly, setDeniedOnly] = useState(false);
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState<"loading" | "error" | "unauthorized" | "ready">(
    "loading",
  );

  // A filter change re-pages to the start - an offset from the old filter's
  // result set is almost certainly out of range for the new one.
  useEffect(() => {
    setOffset(0);
  }, [batchRunId, statusFilter, stageFilter, deniedOnly, limit]);

  useEffect(() => {
    let cancelled = false;

    fetchCollectionAttempts({
      batch_run_id: batchRunId || undefined,
      status: statusFilter || undefined,
      failure_stage: stageFilter || undefined,
      source_denied: deniedOnly ? true : undefined,
      limit,
      offset,
    })
      .then((data) => {
        if (cancelled) return;
        setAttempts(data.attempts);
        setSummary(data.summary);
        setTotal(data.pagination.total);
        setStatus("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        setStatus(err instanceof AdminAuthRequiredError ? "unauthorized" : "error");
      });

    return () => {
      cancelled = true;
    };
  }, [batchRunId, statusFilter, stageFilter, deniedOnly, limit, offset]);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <PageHeader
          title="Collection attempts"
          description="Durable per-mapping record of what each collector batch tried and what became of it. Read-only."
          actions={
            status === "ready" ? (
              <span className="text-sm text-text-muted">
                {total} attempt{total === 1 ? "" : "s"}
              </span>
            ) : null
          }
        />

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap gap-1">
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

          <label className="sr-only" htmlFor="stage-filter">
            Failure stage
          </label>
          <select
            id="stage-filter"
            value={stageFilter}
            onChange={(e) => setStageFilter(e.target.value)}
            className="rounded-control bg-bg-surface px-2 py-1 text-xs text-text-secondary ring-1 ring-inset ring-border-default"
          >
            {STAGE_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>

          <label className="flex items-center gap-1.5 text-xs text-text-secondary">
            <input
              type="checkbox"
              checked={deniedOnly}
              onChange={(e) => setDeniedOnly(e.target.checked)}
            />
            Source denied only
          </label>

          <label className="sr-only" htmlFor="batch-filter">
            Batch run id
          </label>
          <input
            id="batch-filter"
            type="text"
            value={batchRunId}
            placeholder="batch run id"
            onChange={(e) => setBatchRunId(e.target.value.trim())}
            className="mono rounded-control bg-bg-surface px-2 py-1 text-xs text-text-primary ring-1 ring-inset ring-border-default"
          />
          {batchRunId && (
            <button
              type="button"
              onClick={() => setBatchRunId("")}
              className="text-xs text-sky-400 hover:underline"
            >
              Clear batch
            </button>
          )}
        </div>

        {status === "unauthorized" && <AdminSessionExpired />}
        {status === "loading" && <LoadingState>Loading collection attempts…</LoadingState>}
        {status === "error" && (
          <ErrorState>
            Failed to load collection attempts from the API. Is the backend running?
          </ErrorState>
        )}

        {status === "ready" && (
          <>
            {summary && summary.total_attempts > 0 && (
              <BatchSummary summary={summary} batchRunId={batchRunId} />
            )}

            <DataTableShell
              isEmpty={attempts.length === 0}
              emptyLabel="No collection attempts recorded yet."
            >
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Batch</th>
                    <th className="text-right">#</th>
                    <th>Card / mapping</th>
                    <th>Status</th>
                    <th>Stage</th>
                    <th>Reason</th>
                    <th>Denied</th>
                    <th className="text-right">Duration</th>
                    <th className="text-right">Obs</th>
                  </tr>
                </thead>
                <tbody>
                  {attempts.map((a) => (
                    <tr key={a.id}>
                      <td className="whitespace-nowrap">{formatDateTime(a.selected_at)}</td>
                      <td>
                        <button
                          type="button"
                          onClick={() => setBatchRunId(a.batch_run_id)}
                          className="mono text-xs text-sky-400 hover:underline"
                          title="Filter to this batch"
                        >
                          {a.batch_run_id}
                        </button>
                      </td>
                      <td className="mono text-right text-xs">{a.selection_ordinal}</td>
                      <td>
                        {a.card_code ? (
                          <span className="mono text-xs">{a.card_code}</span>
                        ) : (
                          <span className="text-xs text-text-muted" title="Mapping no longer resolvable">
                            unresolved
                          </span>
                        )}{" "}
                        <span className="mono text-xs text-text-muted">
                          #{a.source_card_mapping_id}
                        </span>
                      </td>
                      <td className={`whitespace-nowrap text-xs ${statusTone(a.status)}`}>
                        {a.status}
                      </td>
                      <td className="mono text-xs text-text-secondary">
                        {a.failure_stage ?? "—"}
                      </td>
                      <td
                        className="max-w-[22rem] truncate text-xs text-text-secondary"
                        title={a.failure_reason ?? undefined}
                      >
                        {a.failure_reason ?? "—"}
                      </td>
                      <td className="text-xs">
                        {a.source_denied ? (
                          <span className="text-red-400">denied</span>
                        ) : (
                          <span className="text-text-muted">—</span>
                        )}
                      </td>
                      <td className="mono text-right text-xs">
                        {formatDuration(a.duration_seconds)}
                      </td>
                      <td className="mono text-right text-xs">
                        {a.price_observation_id ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </DataTableShell>

            <PaginationControls
              total={total}
              limit={limit}
              offset={offset}
              limitOptions={[...LIMIT_OPTIONS]}
              onLimitChange={setLimit}
              onOffsetChange={setOffset}
            />
          </>
        )}
      </main>
    </div>
  );
}
