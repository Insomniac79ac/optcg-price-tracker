"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { ErrorState, LoadingState } from "@/components/StateBlocks";
import { VersionFooter } from "@/components/VersionFooter";
import { ActionButton } from "@/components/ui/ActionButton";
import { Badge } from "@/components/ui/Badge";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { FILTER_INPUT_CLASS } from "@/components/ui/FilterBar";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  AdminAuthRequiredError,
  AdminNetworkError,
  AdminNotFoundError,
  AdminProxyError,
  AdminTimeoutError,
  type JobLock,
  cleanupExpiredJobLocks,
  fetchJobLocks,
  forceReleaseJobLock,
} from "@/lib/api";

type PageStatus =
  | "loading"
  | "ready"
  | "unauthorized"
  | "not_found"
  | "timeout"
  | "network_error"
  | "proxy_error"
  | "error";

interface ProxyErrorDetails {
  message: string;
  backendStatus?: number;
  bodyPreview?: string;
}

const RELEASE_CONFIRM_PHRASE = "RELEASE";

export default function JobLocksPage() {
  const [locks, setLocks] = useState<JobLock[] | null>(null);
  const [status, setStatus] = useState<PageStatus>("loading");
  const [proxyError, setProxyError] = useState<ProxyErrorDetails | null>(null);

  const [cleanupPending, setCleanupPending] = useState(false);
  const [cleanupMessage, setCleanupMessage] = useState<string | null>(null);
  const [cleanupError, setCleanupError] = useState<string | null>(null);

  const [releaseTarget, setReleaseTarget] = useState<string | null>(null);
  const [releaseConfirmText, setReleaseConfirmText] = useState("");
  const [releasePending, setReleasePending] = useState(false);
  const [releaseError, setReleaseError] = useState<string | null>(null);
  const [releaseMessage, setReleaseMessage] = useState<string | null>(null);

  function load() {
    setStatus("loading");
    fetchJobLocks()
      .then((data) => {
        setLocks(data.locks);
        setStatus("ready");
      })
      .catch((err) => {
        if (err instanceof AdminAuthRequiredError) setStatus("unauthorized");
        else if (err instanceof AdminNotFoundError) setStatus("not_found");
        else if (err instanceof AdminTimeoutError) setStatus("timeout");
        else if (err instanceof AdminNetworkError) setStatus("network_error");
        else if (err instanceof AdminProxyError) {
          setProxyError({
            message: err.message,
            backendStatus: err.backendStatus,
            bodyPreview: err.bodyPreview,
          });
          setStatus("proxy_error");
        } else setStatus("error");
      });
  }

  useEffect(() => {
    load();
  }, []);

  async function handleCleanupExpired() {
    setCleanupPending(true);
    setCleanupError(null);
    setCleanupMessage(null);
    try {
      const result = await cleanupExpiredJobLocks();
      setCleanupMessage(
        result.cleaned_up_count === 0
          ? "No expired locks to clean up."
          : `Marked ${result.cleaned_up_count} expired lock(s) as expired.`,
      );
      load();
    } catch (err) {
      setCleanupError(err instanceof Error ? err.message : "Failed to clean up expired locks.");
    } finally {
      setCleanupPending(false);
    }
  }

  function beginRelease(lockName: string) {
    setReleaseTarget(lockName);
    setReleaseConfirmText("");
    setReleaseError(null);
    setReleaseMessage(null);
  }

  function cancelRelease() {
    setReleaseTarget(null);
    setReleaseConfirmText("");
    setReleaseError(null);
  }

  async function confirmRelease(lockName: string) {
    if (releaseConfirmText !== RELEASE_CONFIRM_PHRASE) {
      setReleaseError(`Type ${RELEASE_CONFIRM_PHRASE} to confirm.`);
      return;
    }
    setReleasePending(true);
    setReleaseError(null);
    try {
      const result = await forceReleaseJobLock(lockName, releaseConfirmText);
      setReleaseMessage(
        result.released
          ? `Force-released lock: ${result.lock_name}`
          : `Lock ${result.lock_name} was not active - nothing to release.`,
      );
      setReleaseTarget(null);
      setReleaseConfirmText("");
      load();
    } catch (err) {
      setReleaseError(err instanceof Error ? err.message : "Failed to force-release lock.");
    } finally {
      setReleasePending(false);
    }
  }

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <PageHeader
          title="Job Locks"
          description="Prevents overlapping refreshes, workflows, and maintenance jobs."
          actions={<AdminLogoutButton />}
        />

        {status === "unauthorized" && (
          <AdminAuthGate onTokenSaved={() => window.location.reload()} />
        )}

        {status === "loading" && <LoadingState>Loading job locks…</LoadingState>}

        {status === "not_found" && (
          <ErrorState>
            The job locks endpoint was not found (404). Is the backend up to date?
          </ErrorState>
        )}

        {status === "timeout" && (
          <ErrorState>
            Timed out waiting for job locks (15s). Is the backend running and reachable?
          </ErrorState>
        )}

        {status === "network_error" && (
          <ErrorState>
            Could not reach the API proxy. Check that the web and api containers are both
            running.
          </ErrorState>
        )}

        {status === "proxy_error" && proxyError && (
          <ErrorState>
            <p className="font-medium">{proxyError.message}</p>
            {proxyError.backendStatus !== undefined && (
              <p className="mt-1">backend_status: {proxyError.backendStatus}</p>
            )}
            {proxyError.bodyPreview && (
              <pre className="mt-3 max-h-48 overflow-auto rounded-control border border-signal-red/40 bg-signal-red/10 p-3 text-left text-xs whitespace-pre-wrap text-signal-red">
                {proxyError.bodyPreview}
              </pre>
            )}
          </ErrorState>
        )}

        {status === "error" && (
          <ErrorState>Failed to load job locks. Is the backend running?</ErrorState>
        )}

        {status === "ready" && locks && (
          <>
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <ActionButton onClick={handleCleanupExpired} disabled={cleanupPending}>
                {cleanupPending ? "Cleaning up…" : "Cleanup expired locks"}
              </ActionButton>
              {cleanupMessage && <span className="text-xs text-signal-green">{cleanupMessage}</span>}
              {cleanupError && <span className="text-xs text-signal-red">{cleanupError}</span>}
            </div>

            <div className="mb-4 rounded-control border border-signal-warning/40 bg-signal-warning/10 px-3 py-2 text-xs text-signal-warning">
              Only force release if you are sure the job is no longer running.
            </div>

            {releaseMessage && (
              <div className="mb-4 rounded-control border border-signal-green/40 bg-signal-green/10 px-3 py-2 text-xs text-signal-green">
                {releaseMessage}
              </div>
            )}

            <DataTableShell isEmpty={locks.length === 0} emptyLabel="No active job locks.">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Lock name</th>
                    <th>Owner</th>
                    <th>Acquired at</th>
                    <th>Expires at</th>
                    <th>Status</th>
                    <th>Metadata</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {locks.map((lock) => (
                    <tr key={lock.lock_name}>
                      <td className="mono text-text-secondary">{lock.lock_name}</td>
                      <td className="mono text-text-secondary">{lock.owner_id}</td>
                      <td className="mono whitespace-nowrap text-text-secondary">
                        {new Date(lock.acquired_at).toLocaleString()}
                      </td>
                      <td className="mono whitespace-nowrap text-text-secondary">
                        {new Date(lock.expires_at).toLocaleString()}
                      </td>
                      <td>
                        <Badge
                          label={lock.status}
                          className="bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/30"
                        />
                      </td>
                      <td className="text-text-secondary">
                        {lock.metadata ? (
                          <code className="text-[11px]">{JSON.stringify(lock.metadata)}</code>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>
                        {releaseTarget === lock.lock_name ? (
                          <div className="flex flex-col gap-1.5">
                            <span className="text-[11px] text-text-secondary">
                              Type {RELEASE_CONFIRM_PHRASE} to confirm:
                            </span>
                            <div className="flex items-center gap-1.5">
                              <input
                                type="text"
                                value={releaseConfirmText}
                                onChange={(e) => setReleaseConfirmText(e.target.value)}
                                className={`w-24 ${FILTER_INPUT_CLASS}`}
                              />
                              <ActionButton
                                variant="danger"
                                onClick={() => confirmRelease(lock.lock_name)}
                                disabled={releasePending}
                              >
                                {releasePending ? "Releasing…" : "Confirm"}
                              </ActionButton>
                              <ActionButton onClick={cancelRelease} disabled={releasePending}>
                                Cancel
                              </ActionButton>
                            </div>
                            {releaseError && (
                              <span className="text-[11px] text-signal-red">{releaseError}</span>
                            )}
                          </div>
                        ) : (
                          <ActionButton variant="real" onClick={() => beginRelease(lock.lock_name)}>
                            Force release
                          </ActionButton>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </DataTableShell>

            <div className="mt-4 flex flex-wrap gap-3 text-xs text-text-muted">
              <Link href="/admin/performance" className="text-sky-400 hover:underline">
                Performance
              </Link>
              <Link href="/admin/cache" className="text-sky-400 hover:underline">
                Cache
              </Link>
              <Link href="/admin/data-retention" className="text-sky-400 hover:underline">
                Data retention
              </Link>
              <Link href="/admin/file-jobs" className="text-sky-400 hover:underline">
                File jobs
              </Link>
              <Link href="/admin/actions" className="text-sky-400 hover:underline">
                Admin actions
              </Link>
              <Link href="/admin/market-workflow-runs" className="text-sky-400 hover:underline">
                Workflow runs
              </Link>
              <Link href="/admin/refresh-runs" className="text-sky-400 hover:underline">
                Refresh runs
              </Link>
              <Link href="/admin/logs" className="text-sky-400 hover:underline">
                App logs
              </Link>
            </div>
          </>
        )}
        <VersionFooter />
      </main>
    </div>
  );
}
