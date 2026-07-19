"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { ErrorState, LoadingState } from "@/components/StateBlocks";
import { VersionFooter } from "@/components/VersionFooter";
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
        <div className="mb-1 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">Job Locks</h1>
          <AdminLogoutButton />
        </div>
        <p className="mb-6 text-xs text-neutral-500">
          Prevents overlapping refreshes, workflows, and maintenance jobs.
        </p>

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
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-6 text-sm text-rose-300">
            <p className="font-medium">{proxyError.message}</p>
            {proxyError.backendStatus !== undefined && (
              <p className="mt-1 text-rose-400">backend_status: {proxyError.backendStatus}</p>
            )}
            {proxyError.bodyPreview && (
              <pre className="mt-3 max-h-48 overflow-auto rounded border border-rose-900/50 bg-rose-950/40 p-3 text-xs whitespace-pre-wrap text-rose-200">
                {proxyError.bodyPreview}
              </pre>
            )}
          </div>
        )}

        {status === "error" && (
          <ErrorState>Failed to load job locks. Is the backend running?</ErrorState>
        )}

        {status === "ready" && locks && (
          <>
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={handleCleanupExpired}
                disabled={cleanupPending}
                className="rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-200 hover:text-neutral-100 disabled:opacity-50"
              >
                {cleanupPending ? "Cleaning up…" : "Cleanup expired locks"}
              </button>
              {cleanupMessage && <span className="text-xs text-emerald-400">{cleanupMessage}</span>}
              {cleanupError && <span className="text-xs text-rose-400">{cleanupError}</span>}
            </div>

            <div className="mb-4 rounded border border-amber-900/50 bg-amber-950/20 px-3 py-2 text-xs text-amber-300">
              Only force release if you are sure the job is no longer running.
            </div>

            {releaseMessage && (
              <div className="mb-4 rounded border border-emerald-900/50 bg-emerald-950/20 px-3 py-2 text-xs text-emerald-300">
                {releaseMessage}
              </div>
            )}

            <div className="overflow-x-auto rounded-lg border border-neutral-800">
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                    <th className="px-3 py-2 font-medium">Lock name</th>
                    <th className="px-3 py-2 font-medium">Owner</th>
                    <th className="px-3 py-2 font-medium">Acquired at</th>
                    <th className="px-3 py-2 font-medium">Expires at</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2 font-medium">Metadata</th>
                    <th className="px-3 py-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {locks.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="px-3 py-6 text-center text-neutral-500">
                        No active job locks.
                      </td>
                    </tr>
                  ) : (
                    locks.map((lock) => (
                      <tr
                        key={lock.lock_name}
                        className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                      >
                        <td className="px-3 py-2 font-mono text-neutral-300">{lock.lock_name}</td>
                        <td className="px-3 py-2 font-mono text-neutral-400">{lock.owner_id}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-neutral-400">
                          {new Date(lock.acquired_at).toLocaleString()}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-neutral-400">
                          {new Date(lock.expires_at).toLocaleString()}
                        </td>
                        <td className="px-3 py-2">
                          <span className="inline-flex items-center rounded bg-emerald-500/15 px-1.5 py-0.5 text-xs font-medium text-emerald-300 ring-1 ring-inset ring-emerald-500/30">
                            {lock.status}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-neutral-400">
                          {lock.metadata ? (
                            <code className="text-[11px]">{JSON.stringify(lock.metadata)}</code>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="px-3 py-2">
                          {releaseTarget === lock.lock_name ? (
                            <div className="flex flex-col gap-1.5">
                              <span className="text-[11px] text-neutral-400">
                                Type {RELEASE_CONFIRM_PHRASE} to confirm:
                              </span>
                              <div className="flex items-center gap-1.5">
                                <input
                                  type="text"
                                  value={releaseConfirmText}
                                  onChange={(e) => setReleaseConfirmText(e.target.value)}
                                  className="w-24 rounded border border-neutral-700 bg-neutral-950 px-1.5 py-1 text-xs text-neutral-100"
                                />
                                <button
                                  type="button"
                                  onClick={() => confirmRelease(lock.lock_name)}
                                  disabled={releasePending}
                                  className="rounded bg-rose-600 px-2 py-1 text-xs font-medium text-white hover:bg-rose-500 disabled:opacity-50"
                                >
                                  {releasePending ? "Releasing…" : "Confirm"}
                                </button>
                                <button
                                  type="button"
                                  onClick={cancelRelease}
                                  disabled={releasePending}
                                  className="rounded border border-neutral-700 px-2 py-1 text-xs font-medium text-neutral-300 hover:text-neutral-100 disabled:opacity-50"
                                >
                                  Cancel
                                </button>
                              </div>
                              {releaseError && (
                                <span className="text-[11px] text-rose-400">{releaseError}</span>
                              )}
                            </div>
                          ) : (
                            <button
                              type="button"
                              onClick={() => beginRelease(lock.lock_name)}
                              className="rounded border border-rose-900/50 px-2 py-1 text-xs font-medium text-rose-300 hover:text-rose-200"
                            >
                              Force release
                            </button>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <div className="mt-4 flex flex-wrap gap-3 text-xs">
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
                href="/admin/data-retention"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Data retention
              </Link>
              <Link
                href="/admin/file-jobs"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                File jobs
              </Link>
              <Link
                href="/admin/actions"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Admin actions
              </Link>
              <Link
                href="/admin/market-workflow-runs"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Workflow runs
              </Link>
              <Link
                href="/admin/refresh-runs"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Refresh runs
              </Link>
              <Link
                href="/admin/logs"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
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
