"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import {
  AdminAuthRequiredError,
  AdminNetworkError,
  AdminNotFoundError,
  AdminProxyError,
  AdminTimeoutError,
  type ReleaseStatus,
  fetchReleaseStatus,
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

const STATUS_STYLES: Record<string, string> = {
  ok: "text-emerald-400",
  warning: "text-amber-400",
  critical: "text-rose-400",
};

export default function ReleaseStatusPage() {
  const [status, setStatus] = useState<ReleaseStatus | null>(null);
  const [pageStatus, setPageStatus] = useState<PageStatus>("loading");
  const [proxyError, setProxyError] = useState<ProxyErrorDetails | null>(null);

  function load() {
    setPageStatus("loading");
    fetchReleaseStatus()
      .then((data) => {
        setStatus(data);
        setPageStatus("ready");
      })
      .catch((err) => {
        if (err instanceof AdminAuthRequiredError) setPageStatus("unauthorized");
        else if (err instanceof AdminNotFoundError) setPageStatus("not_found");
        else if (err instanceof AdminTimeoutError) setPageStatus("timeout");
        else if (err instanceof AdminNetworkError) setPageStatus("network_error");
        else if (err instanceof AdminProxyError) {
          setProxyError({
            message: err.message,
            backendStatus: err.backendStatus,
            bodyPreview: err.bodyPreview,
          });
          setPageStatus("proxy_error");
        } else setPageStatus("error");
      });
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <div className="mb-4 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">Release status</h1>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={load}
              className="rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-200 hover:text-neutral-100"
            >
              Refresh
            </button>
            <AdminLogoutButton />
          </div>
        </div>
        <p className="mb-4 text-sm text-neutral-500">
          Version/build metadata plus the latest system check, workflow run, backup, and error -
          the same checklist as docs/release_checklist.md&apos;s post-deploy validation step.
        </p>

        {pageStatus === "unauthorized" && (
          <AdminAuthGate onTokenSaved={() => window.location.reload()} />
        )}

        {pageStatus === "loading" && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            Loading release status…
          </div>
        )}

        {pageStatus === "not_found" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            The release-status endpoint was not found (404). Is the backend up to date?
          </div>
        )}

        {pageStatus === "timeout" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Timed out waiting for release status (15s). Is the backend running and reachable?
          </div>
        )}

        {pageStatus === "network_error" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Could not reach the API proxy. Check that the web and api containers are both
            running.
          </div>
        )}

        {pageStatus === "proxy_error" && proxyError && (
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

        {pageStatus === "error" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Failed to load release status. Is the backend running?
          </div>
        )}

        {pageStatus === "ready" && status && (
          <>
            <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <InfoCard label="Version" value={status.version} mono />
              <InfoCard label="Git commit" value={status.git_commit} mono />
              <InfoCard label="Build time" value={status.build_time} mono />
              <InfoCard label="App env" value={status.app_env} />
            </div>

            <div className="mb-6 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
              <h2 className="mb-3 text-sm font-semibold text-neutral-200">Release readiness</h2>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <div>
                  <div className="text-xs uppercase tracking-wide text-neutral-500">
                    System check status
                  </div>
                  <div
                    className={`mt-1 text-lg font-semibold uppercase ${
                      STATUS_STYLES[status.release_readiness.system_check_status] ??
                      "text-neutral-100"
                    }`}
                  >
                    {status.release_readiness.system_check_status}
                  </div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wide text-neutral-500">
                    Critical logs (24h)
                  </div>
                  <div
                    className={`mt-1 text-lg font-semibold ${
                      status.release_readiness.critical_logs_last_24h > 0
                        ? "text-rose-400"
                        : "text-neutral-100"
                    }`}
                  >
                    {status.release_readiness.critical_logs_last_24h}
                  </div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wide text-neutral-500">
                    Latest backup available
                  </div>
                  <div
                    className={`mt-1 text-lg font-semibold ${
                      status.release_readiness.latest_backup_available
                        ? "text-emerald-400"
                        : "text-amber-400"
                    }`}
                  >
                    {status.release_readiness.latest_backup_available ? "Yes" : "No"}
                  </div>
                </div>
              </div>
            </div>

            <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-2">
              <Section title="Latest system check">
                <div className="mb-2 flex items-center gap-2">
                  <span
                    className={`text-sm font-semibold uppercase ${
                      STATUS_STYLES[status.latest_system_check.status] ?? "text-neutral-100"
                    }`}
                  >
                    {status.latest_system_check.status}
                  </span>
                  <span className="text-xs text-neutral-500">
                    {status.latest_system_check.summary.checks_passed}/
                    {status.latest_system_check.summary.checks_total} checks passed
                    {status.latest_system_check.summary.warnings > 0 &&
                      `, ${status.latest_system_check.summary.warnings} warning(s)`}
                    {status.latest_system_check.summary.critical > 0 &&
                      `, ${status.latest_system_check.summary.critical} critical`}
                  </span>
                </div>
                <Link
                  href="/admin/system-check"
                  className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
                >
                  View full system check
                </Link>
              </Section>

              <Section title="Latest market workflow run">
                {status.latest_market_workflow_run ? (
                  <div className="text-xs text-neutral-400">
                    <p>
                      Run #{String(status.latest_market_workflow_run.id)} -{" "}
                      <span className="font-medium text-neutral-200">
                        {String(status.latest_market_workflow_run.status)}
                      </span>
                    </p>
                    <p className="mt-1">
                      Started: {String(status.latest_market_workflow_run.started_at)}
                    </p>
                    {status.latest_market_workflow_run.error_message ? (
                      <p className="mt-1 text-rose-300">
                        {String(status.latest_market_workflow_run.error_message)}
                      </p>
                    ) : null}
                  </div>
                ) : (
                  <p className="text-xs text-neutral-500">No workflow runs yet.</p>
                )}
                <Link
                  href="/admin/market-workflow-runs"
                  className="mt-2 inline-block text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
                >
                  View workflow runs
                </Link>
              </Section>

              <Section title="Latest backup">
                {status.latest_backup ? (
                  <div className="text-xs text-neutral-400">
                    <p className="font-mono text-neutral-200">
                      {String(status.latest_backup.filename)}
                    </p>
                    <p className="mt-1">
                      {String(status.latest_backup.size_bytes)} bytes - created{" "}
                      {String(status.latest_backup.created_at)}
                    </p>
                  </div>
                ) : (
                  <p className="text-xs text-neutral-500">No backups found.</p>
                )}
                <Link
                  href="/admin/backup"
                  className="mt-2 inline-block text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
                >
                  View backup &amp; restore
                </Link>
              </Section>

              <Section title="Latest error">
                {status.latest_error ? (
                  <div className="text-xs text-neutral-400">
                    <p className="font-medium text-rose-300">{status.latest_error.message}</p>
                    <p className="mt-1">
                      {status.latest_error.level} - {status.latest_error.service} -{" "}
                      {status.latest_error.created_at}
                    </p>
                  </div>
                ) : (
                  <p className="text-xs text-neutral-500">No errors recorded.</p>
                )}
                <Link
                  href="/admin/logs"
                  className="mt-2 inline-block text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
                >
                  View app logs
                </Link>
              </Section>
            </div>

            <div className="flex flex-wrap gap-3 text-xs">
              <Link
                href="/admin/system-check"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                System check
              </Link>
              <Link
                href="/admin/logs"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                App logs
              </Link>
              <Link
                href="/admin/backup"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Backup &amp; restore
              </Link>
              <Link
                href="/admin/market-workflow-runs"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Market workflow runs
              </Link>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function InfoCard({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div
        className={`mt-1 truncate text-sm font-semibold text-neutral-100 ${mono ? "font-mono" : ""}`}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <h2 className="mb-2 text-sm font-semibold text-neutral-200">{title}</h2>
      {children}
    </div>
  );
}
