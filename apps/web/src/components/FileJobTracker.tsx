"use client";

import { useEffect, useRef, useState } from "react";

import { type FileJob, cancelFileJob, downloadFileJob, fetchFileJob } from "@/lib/api";
import { ActionButton } from "@/components/ui/ActionButton";
import { Badge } from "@/components/ui/Badge";
import { TableScrollContainer } from "@/components/ui/DataTableShell";

const POLL_INTERVAL_MS = 1500;
const ACTIVE_STATUSES = new Set(["queued", "running"]);

const STATUS_STYLES: Record<string, string> = {
  queued: "bg-neutral-500/15 text-neutral-300 ring-1 ring-inset ring-neutral-500/30",
  running: "bg-sky-500/15 text-sky-300 ring-1 ring-inset ring-sky-500/30",
  success: "bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/30",
  failed: "bg-rose-500/15 text-rose-300 ring-1 ring-inset ring-rose-500/30",
  cancelled: "bg-amber-500/15 text-amber-300 ring-1 ring-inset ring-amber-500/30",
};

/** Polls GET /file-jobs/{id} while the job is queued/running and renders
 * its progress/status/errors/download link - the shared piece behind the
 * collection/wishlist background import/export UI and the admin backup
 * page's background export option. See 'Large import/export jobs' in
 * docs/operations.md.
 *
 * `onSuccess` fires once, the first time the job reaches status=success -
 * callers use it to refresh whatever list/summary the job just changed
 * (e.g. a completed background import). */
export function FileJobTracker({
  fileJobId,
  onSuccess,
}: {
  fileJobId: number;
  onSuccess?: (job: FileJob) => void;
}) {
  const [job, setJob] = useState<FileJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloadPending, setDownloadPending] = useState(false);
  const [cancelPending, setCancelPending] = useState(false);
  const notifiedSuccessRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    notifiedSuccessRef.current = false;

    async function poll() {
      try {
        const data = await fetchFileJob(fileJobId);
        if (cancelled) return;
        setJob(data);
        setError(null);
        if (data.status === "success" && !notifiedSuccessRef.current) {
          notifiedSuccessRef.current = true;
          onSuccess?.(data);
        }
        if (ACTIVE_STATUSES.has(data.status)) {
          timer = setTimeout(poll, POLL_INTERVAL_MS);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to check job status.");
        }
      }
    }

    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileJobId]);

  async function handleDownload() {
    setDownloadError(null);
    setDownloadPending(true);
    try {
      await downloadFileJob(fileJobId);
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : "Failed to download file.");
    } finally {
      setDownloadPending(false);
    }
  }

  async function handleCancel() {
    setCancelPending(true);
    try {
      const updated = await cancelFileJob(fileJobId);
      setJob((prev) => (prev ? { ...prev, status: updated.status as FileJob["status"] } : prev));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel job.");
    } finally {
      setCancelPending(false);
    }
  }

  if (error) {
    return (
      <div className="mt-3 rounded border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
        {error}
      </div>
    );
  }

  if (!job) {
    return <p className="mt-3 text-xs text-neutral-500">Checking job status…</p>;
  }

  const progressLabel =
    job.progress_total !== null
      ? `${job.progress_current}/${job.progress_total}`
      : job.progress_current > 0
        ? String(job.progress_current)
        : null;

  return (
    <div className="mt-3 rounded border border-neutral-800 bg-neutral-950 p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-neutral-500">File job #{job.id}</span>
        <Badge
          label={job.status}
          className={STATUS_STYLES[job.status] ?? "bg-neutral-500/15 text-neutral-300 ring-1 ring-inset ring-neutral-500/30"}
        />
        {progressLabel && <span className="text-neutral-400">rows: {progressLabel}</span>}

        {job.download_ready && (
          <ActionButton
            variant="primary"
            onClick={handleDownload}
            disabled={downloadPending}
            className="ml-auto"
          >
            {downloadPending ? "Downloading…" : "Download"}
          </ActionButton>
        )}
        {ACTIVE_STATUSES.has(job.status) && (
          <ActionButton
            variant="default"
            onClick={handleCancel}
            disabled={cancelPending}
            className={job.download_ready ? "" : "ml-auto"}
          >
            {cancelPending ? "Cancelling…" : "Cancel"}
          </ActionButton>
        )}
      </div>

      {downloadError && <p className="mt-2 text-rose-300">{downloadError}</p>}

      {job.summary && Object.keys(job.summary).length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {Object.entries(job.summary)
            .filter(([, v]) => typeof v === "number" || typeof v === "string")
            .map(([key, value]) => (
              <span key={key} className="rounded-control border border-border-default bg-bg-surface px-2 py-1 text-text-secondary">
                <span className="text-text-muted">{key}:</span> {String(value)}
              </span>
            ))}
        </div>
      )}

      {Array.isArray(job.errors) && job.errors.length > 0 && (
        <TableScrollContainer showScrollHint={false} className="mt-2 border-signal-red/40">
          <table className="data-table">
            <tbody>
              {job.errors.map((e, idx) => (
                <tr key={idx}>
                  <td className="text-signal-red">
                    {typeof e === "object" && e !== null
                      ? `${e.row_number ? `Row ${e.row_number}: ` : ""}${e.error ?? JSON.stringify(e)}`
                      : String(e)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScrollContainer>
      )}
    </div>
  );
}
