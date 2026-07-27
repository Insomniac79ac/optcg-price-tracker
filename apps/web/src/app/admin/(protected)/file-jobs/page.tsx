"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminSessionExpired } from "@/components/AdminSessionExpired";
import { AppHeader } from "@/components/AppHeader";
import { ActionButton } from "@/components/ui/ActionButton";
import { Badge } from "@/components/ui/Badge";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { FILTER_INPUT_CLASS } from "@/components/ui/FilterBar";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  AdminAuthRequiredError,
  FILE_JOB_STATUSES,
  FILE_JOB_TYPES,
  type FileJob,
  cancelFileJob,
  cleanupFileJobs,
  downloadFileJob,
  fetchFileJobs,
} from "@/lib/api";

const CLEANUP_CONFIRM_PHRASE = "CLEANUP";

const STATUS_STYLES: Record<string, string> = {
  queued: "bg-neutral-500/15 text-neutral-300 ring-1 ring-inset ring-neutral-500/30",
  running: "bg-sky-500/15 text-sky-300 ring-1 ring-inset ring-sky-500/30",
  success: "bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/30",
  failed: "bg-rose-500/15 text-rose-300 ring-1 ring-inset ring-rose-500/30",
  cancelled: "bg-amber-500/15 text-amber-300 ring-1 ring-inset ring-amber-500/30",
};

const HELPFUL_LIMIT = 50;

export default function FileJobsPage() {
  const [unauthorized, setUnauthorized] = useState(false);
  const [jobs, setJobs] = useState<FileJob[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [jobTypeFilter, setJobTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingActionId, setPendingActionId] = useState<number | null>(null);

  function load() {
    fetchFileJobs({
      job_type: jobTypeFilter || undefined,
      status: statusFilter || undefined,
      limit: HELPFUL_LIMIT,
    })
      .then((data) => {
        setJobs(data.jobs);
        setTotal(data.total);
        setError(null);
      })
      .catch((err) => {
        if (err instanceof AdminAuthRequiredError) {
          setUnauthorized(true);
        } else {
          setError(err instanceof Error ? err.message : "Failed to load file jobs.");
        }
      });
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobTypeFilter, statusFilter]);

  async function handleDownload(job: FileJob) {
    setActionError(null);
    setPendingActionId(job.id);
    try {
      await downloadFileJob(job.id);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to download file.");
    } finally {
      setPendingActionId(null);
    }
  }

  async function handleCancel(job: FileJob) {
    setActionError(null);
    setPendingActionId(job.id);
    try {
      await cancelFileJob(job.id);
      load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to cancel job.");
    } finally {
      setPendingActionId(null);
    }
  }

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-6xl px-4 py-6">
        <PageHeader
          title="File jobs"
          description={
            <>
              Background collection/wishlist import/export and backup export jobs - see
              &quot;Large import/export jobs&quot; in docs/operations.md.
            </>
          }
        />

        {unauthorized && (
          <AdminSessionExpired />
        )}

        {!unauthorized && (
          <div className="flex flex-col gap-6">
            <section className="panel p-4">
              <div className="mb-3 flex flex-wrap items-center gap-3">
                <h2 className="text-sm font-semibold text-text-primary">Jobs</h2>
                <label className="ml-auto flex items-center gap-1.5 text-xs text-text-secondary">
                  Type
                  <select
                    value={jobTypeFilter}
                    onChange={(e) => setJobTypeFilter(e.target.value)}
                    className={FILTER_INPUT_CLASS}
                  >
                    <option value="">All</option>
                    {FILE_JOB_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex items-center gap-1.5 text-xs text-text-secondary">
                  Status
                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    className={FILTER_INPUT_CLASS}
                  >
                    <option value="">All</option>
                    {FILE_JOB_STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </label>
                <ActionButton onClick={load}>Refresh</ActionButton>
              </div>

              {error && (
                <div className="mb-3 rounded-control border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
                  {error}
                </div>
              )}
              {actionError && (
                <div className="mb-3 rounded-control border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
                  {actionError}
                </div>
              )}

              <DataTableShell isEmpty={!jobs || jobs.length === 0} emptyLabel={!jobs ? "Loading file jobs…" : "No file jobs found."}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Type</th>
                      <th>Status</th>
                      <th>Filename</th>
                      <th>Progress</th>
                      <th>Created</th>
                      <th>Started</th>
                      <th>Finished</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs?.map((job) => (
                      <tr key={job.id}>
                        <td className="mono tabular text-text-secondary">{job.id}</td>
                        <td className="mono text-text-secondary">{job.job_type}</td>
                        <td>
                          <Badge
                            label={job.status}
                            className={
                              STATUS_STYLES[job.status] ??
                              "bg-neutral-500/15 text-neutral-300 ring-1 ring-inset ring-neutral-500/30"
                            }
                          />
                        </td>
                        <td className="text-text-secondary">
                          {job.original_filename ?? job.output_filename ?? "—"}
                        </td>
                        <td className="mono tabular text-text-secondary">
                          {job.progress_total !== null
                            ? `${job.progress_current}/${job.progress_total}`
                            : job.progress_current > 0
                              ? job.progress_current
                              : "—"}
                        </td>
                        <td className="mono whitespace-nowrap text-text-secondary">
                          {new Date(job.created_at).toLocaleString()}
                        </td>
                        <td className="mono whitespace-nowrap text-text-secondary">
                          {job.started_at ? new Date(job.started_at).toLocaleString() : "—"}
                        </td>
                        <td className="mono whitespace-nowrap text-text-secondary">
                          {job.finished_at ? new Date(job.finished_at).toLocaleString() : "—"}
                        </td>
                        <td>
                          <div className="flex flex-wrap gap-2">
                            {job.download_ready && (
                              <ActionButton
                                onClick={() => handleDownload(job)}
                                disabled={pendingActionId === job.id}
                              >
                                Download
                              </ActionButton>
                            )}
                            {(job.status === "queued" || job.status === "running") && (
                              <ActionButton
                                onClick={() => handleCancel(job)}
                                disabled={pendingActionId === job.id}
                              >
                                Cancel
                              </ActionButton>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </DataTableShell>
              <p className="mt-2 text-[11px] text-text-faint">
                Showing {jobs?.length ?? 0} of {total}
              </p>
            </section>

            <CleanupSection onCleaned={load} />

            <div className="flex flex-wrap gap-3 text-xs">
              <Link
                href="/admin/backup"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Backup &amp; restore
              </Link>
              <Link
                href="/admin/performance"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Performance
              </Link>
              <Link
                href="/admin/cache"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Cache
              </Link>
              <Link
                href="/admin/job-locks"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Job locks
              </Link>
              <Link
                href="/admin/data-retention"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Data retention
              </Link>
              <Link
                href="/collection"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Collection
              </Link>
              <Link
                href="/wishlist"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Wishlist
              </Link>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function CleanupSection({ onCleaned }: { onCleaned: () => void }) {
  const [olderThanDays, setOlderThanDays] = useState(7);
  const [dryRun, setDryRun] = useState(true);
  const [confirmText, setConfirmText] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    would_delete: number;
    deleted: number;
  } | null>(null);

  const confirmSatisfied = dryRun || confirmText === CLEANUP_CONFIRM_PHRASE;

  async function handleRun() {
    if (!confirmSatisfied) {
      setError(`Type ${CLEANUP_CONFIRM_PHRASE} to confirm a real cleanup.`);
      return;
    }
    setError(null);
    setPending(true);
    try {
      const data = await cleanupFileJobs({
        older_than_days: olderThanDays,
        dry_run: dryRun,
        confirm: dryRun ? undefined : confirmText,
      });
      setResult({ would_delete: data.would_delete, deleted: data.deleted });
      if (!dryRun) onCleaned();
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) {
        setError("Admin token required.");
      } else {
        setError(err instanceof Error ? err.message : "Failed to run cleanup.");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="panel p-4">
      <h2 className="mb-3 text-sm font-semibold text-text-primary">Cleanup old file jobs</h2>
      <p className="mb-3 text-[11px] text-text-muted">
        Deletes completed/failed/cancelled jobs (and their input/output files) older than the
        given number of days. Queued/running jobs are never touched.
      </p>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          Older than (days)
          <input
            type="number"
            min={1}
            value={olderThanDays}
            onChange={(e) => setOlderThanDays(Number(e.target.value))}
            className={`w-24 ${FILTER_INPUT_CLASS}`}
          />
        </label>

        <label className="flex items-center gap-1.5 rounded-control border border-border-default bg-bg-page px-2 py-1.5 text-xs text-text-secondary">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => {
              setDryRun(e.target.checked);
              setError(null);
            }}
          />
          Dry run
        </label>

        {!dryRun && (
          <label className="flex items-center gap-2 text-xs text-text-secondary">
            Type <span className="mono text-text-primary">{CLEANUP_CONFIRM_PHRASE}</span> to
            confirm:
            <input
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              className={FILTER_INPUT_CLASS}
            />
          </label>
        )}

        <ActionButton variant={dryRun ? "dry-run" : "danger"} onClick={handleRun} disabled={pending}>
          {pending ? "Working…" : dryRun ? "Preview cleanup" : "Run cleanup"}
        </ActionButton>
      </div>

      {error && (
        <div className="mt-3 rounded-control border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <span className="rounded-control border border-border-default bg-bg-page px-2 py-1 text-text-secondary">
            <span className="text-text-muted">Would delete:</span> {result.would_delete}
          </span>
          <span className="rounded-control border border-border-default bg-bg-page px-2 py-1 text-text-secondary">
            <span className="text-text-muted">Deleted:</span> {result.deleted}
          </span>
        </div>
      )}
    </section>
  );
}
