"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import {
  AdminAuthRequiredError,
  FILE_JOB_STATUSES,
  FILE_JOB_TYPES,
  type FileJob,
  cancelFileJob,
  cleanupFileJobs,
  downloadFileJob,
  fetchFileJobs,
  getAdminToken,
} from "@/lib/api";

const CLEANUP_CONFIRM_PHRASE = "CLEANUP";

const STATUS_STYLES: Record<string, string> = {
  queued: "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30",
  running: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  success: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  failed: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  cancelled: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
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
    setUnauthorized(!getAdminToken());
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
        <div className="mb-1 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">File jobs</h1>
          <AdminLogoutButton />
        </div>
        <p className="mb-6 text-xs text-neutral-500">
          Background collection/wishlist import/export and backup export jobs - see &quot;Large
          import/export jobs&quot; in docs/operations.md.
        </p>

        {unauthorized && (
          <AdminAuthGate
            onTokenSaved={() => {
              setUnauthorized(false);
              load();
            }}
          />
        )}

        {!unauthorized && (
          <div className="flex flex-col gap-6">
            <section className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
              <div className="mb-3 flex flex-wrap items-center gap-3">
                <h2 className="text-sm font-semibold text-neutral-200">Jobs</h2>
                <label className="ml-auto flex items-center gap-1.5 text-xs text-neutral-400">
                  Type
                  <select
                    value={jobTypeFilter}
                    onChange={(e) => setJobTypeFilter(e.target.value)}
                    className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                  >
                    <option value="">All</option>
                    {FILE_JOB_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex items-center gap-1.5 text-xs text-neutral-400">
                  Status
                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
                  >
                    <option value="">All</option>
                    {FILE_JOB_STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  onClick={load}
                  className="rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-200 hover:text-neutral-100"
                >
                  Refresh
                </button>
              </div>

              {error && (
                <div className="mb-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
                  {error}
                </div>
              )}
              {actionError && (
                <div className="mb-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
                  {actionError}
                </div>
              )}

              <div className="overflow-x-auto rounded-lg border border-neutral-800">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-neutral-800 bg-neutral-950 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                      <th className="px-3 py-2 font-medium">ID</th>
                      <th className="px-3 py-2 font-medium">Type</th>
                      <th className="px-3 py-2 font-medium">Status</th>
                      <th className="px-3 py-2 font-medium">Filename</th>
                      <th className="px-3 py-2 font-medium">Progress</th>
                      <th className="px-3 py-2 font-medium">Created</th>
                      <th className="px-3 py-2 font-medium">Started</th>
                      <th className="px-3 py-2 font-medium">Finished</th>
                      <th className="px-3 py-2 font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!jobs ? (
                      <tr>
                        <td colSpan={9} className="px-3 py-6 text-center text-neutral-500">
                          Loading file jobs…
                        </td>
                      </tr>
                    ) : jobs.length === 0 ? (
                      <tr>
                        <td colSpan={9} className="px-3 py-6 text-center text-neutral-500">
                          No file jobs found.
                        </td>
                      </tr>
                    ) : (
                      jobs.map((job) => (
                        <tr
                          key={job.id}
                          className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                        >
                          <td className="px-3 py-2 text-neutral-300">{job.id}</td>
                          <td className="px-3 py-2 font-mono text-neutral-300">{job.job_type}</td>
                          <td className="px-3 py-2">
                            <span
                              className={`inline-flex items-center rounded px-1.5 py-0.5 font-medium ring-1 ring-inset ${
                                STATUS_STYLES[job.status] ??
                                "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30"
                              }`}
                            >
                              {job.status}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-neutral-400">
                            {job.original_filename ?? job.output_filename ?? "—"}
                          </td>
                          <td className="px-3 py-2 text-neutral-400">
                            {job.progress_total !== null
                              ? `${job.progress_current}/${job.progress_total}`
                              : job.progress_current > 0
                                ? job.progress_current
                                : "—"}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 text-neutral-400">
                            {new Date(job.created_at).toLocaleString()}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 text-neutral-400">
                            {job.started_at ? new Date(job.started_at).toLocaleString() : "—"}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 text-neutral-400">
                            {job.finished_at ? new Date(job.finished_at).toLocaleString() : "—"}
                          </td>
                          <td className="px-3 py-2">
                            <div className="flex flex-wrap gap-2">
                              {job.download_ready && (
                                <button
                                  type="button"
                                  onClick={() => handleDownload(job)}
                                  disabled={pendingActionId === job.id}
                                  className="rounded border border-neutral-700 px-2 py-1 text-xs font-medium text-neutral-200 hover:text-neutral-100 disabled:opacity-50"
                                >
                                  Download
                                </button>
                              )}
                              {(job.status === "queued" || job.status === "running") && (
                                <button
                                  type="button"
                                  onClick={() => handleCancel(job)}
                                  disabled={pendingActionId === job.id}
                                  className="rounded border border-neutral-700 px-2 py-1 text-xs font-medium text-neutral-300 hover:text-neutral-100 disabled:opacity-50"
                                >
                                  Cancel
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-[11px] text-neutral-600">
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
    <section className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <h2 className="mb-3 text-sm font-semibold text-neutral-200">Cleanup old file jobs</h2>
      <p className="mb-3 text-[11px] text-neutral-500">
        Deletes completed/failed/cancelled jobs (and their input/output files) older than the
        given number of days. Queued/running jobs are never touched.
      </p>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-neutral-400">
          Older than (days)
          <input
            type="number"
            min={1}
            value={olderThanDays}
            onChange={(e) => setOlderThanDays(Number(e.target.value))}
            className="w-24 rounded border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-100"
          />
        </label>

        <label className="flex items-center gap-1.5 rounded border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-xs text-neutral-400">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => {
              setDryRun(e.target.checked);
              setError(null);
            }}
            className="rounded border-neutral-700 bg-neutral-950"
          />
          Dry run
        </label>

        {!dryRun && (
          <label className="flex items-center gap-2 text-xs text-neutral-400">
            Type <span className="font-mono text-neutral-200">{CLEANUP_CONFIRM_PHRASE}</span> to
            confirm:
            <input
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
            />
          </label>
        )}

        <button
          type="button"
          onClick={handleRun}
          disabled={pending}
          className={`rounded px-3 py-1.5 text-xs font-medium disabled:opacity-50 ${
            dryRun
              ? "bg-neutral-100 text-neutral-900 hover:bg-white"
              : "bg-rose-600 text-white hover:bg-rose-500"
          }`}
        >
          {pending ? "Working…" : dryRun ? "Preview cleanup" : "Run cleanup"}
        </button>
      </div>

      {error && (
        <div className="mt-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <span className="rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-neutral-300">
            <span className="text-neutral-500">Would delete:</span> {result.would_delete}
          </span>
          <span className="rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-neutral-300">
            <span className="text-neutral-500">Deleted:</span> {result.deleted}
          </span>
        </div>
      )}
    </section>
  );
}
