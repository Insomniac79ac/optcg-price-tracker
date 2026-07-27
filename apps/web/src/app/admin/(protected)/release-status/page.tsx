"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminSessionExpired } from "@/components/AdminSessionExpired";
import { AppHeader } from "@/components/AppHeader";
import { ErrorState, LoadingState } from "@/components/StateBlocks";
import { ActionButton } from "@/components/ui/ActionButton";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatCard, StatGrid, type StatTone } from "@/components/ui/StatCard";
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

const READINESS_STATUS_TONE: Record<string, StatTone> = {
  ok: "good",
  warning: "bad",
  critical: "bad",
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
        <PageHeader
          title="Release status"
          description={
            <>
              Version/build metadata plus the latest system check, workflow run, backup, and
              error - the same checklist as docs/release_checklist.md&apos;s post-deploy
              validation step.
            </>
          }
          actions={
            <>
              <ActionButton variant="default" onClick={load}>
                Refresh
              </ActionButton>
            </>
          }
        />

        {pageStatus === "unauthorized" && (
          <AdminSessionExpired />
        )}

        {pageStatus === "loading" && <LoadingState>Loading release status…</LoadingState>}

        {pageStatus === "not_found" && (
          <ErrorState>
            The release-status endpoint was not found (404). Is the backend up to date?
          </ErrorState>
        )}

        {pageStatus === "timeout" && (
          <ErrorState>
            Timed out waiting for release status (15s). Is the backend running and reachable?
          </ErrorState>
        )}

        {pageStatus === "network_error" && (
          <ErrorState>
            Could not reach the API proxy. Check that the web and api containers are both
            running.
          </ErrorState>
        )}

        {pageStatus === "proxy_error" && proxyError && (
          <div className="rounded-panel border border-signal-red/40 bg-signal-red/10 p-6 text-sm text-signal-red">
            <p className="font-medium">{proxyError.message}</p>
            {proxyError.backendStatus !== undefined && (
              <p className="mt-1">backend_status: {proxyError.backendStatus}</p>
            )}
            {proxyError.bodyPreview && (
              <pre className="mt-3 max-h-48 overflow-auto rounded-control border border-signal-red/40 bg-signal-red/10 p-3 text-xs whitespace-pre-wrap">
                {proxyError.bodyPreview}
              </pre>
            )}
          </div>
        )}

        {pageStatus === "error" && (
          <ErrorState>Failed to load release status. Is the backend running?</ErrorState>
        )}

        {pageStatus === "ready" && status && (
          <>
            <div className="mb-6">
              <StatGrid>
                <StatCard label="Version" value={status.version} />
                <StatCard label="Git commit" value={status.git_commit} />
                <StatCard label="Build time" value={status.build_time} />
                <StatCard label="App env" value={status.app_env} />
              </StatGrid>
            </div>

            <div className="mb-6 panel p-4">
              <h2 className="mb-3 text-sm font-semibold text-text-primary">Release readiness</h2>
              <StatGrid>
                <StatCard
                  label="System check status"
                  value={status.release_readiness.system_check_status}
                  tone={READINESS_STATUS_TONE[status.release_readiness.system_check_status] ?? "neutral"}
                />
                <StatCard
                  label="Critical logs (24h)"
                  value={status.release_readiness.critical_logs_last_24h}
                  tone={status.release_readiness.critical_logs_last_24h > 0 ? "bad" : "neutral"}
                />
                <StatCard
                  label="Latest backup available"
                  value={status.release_readiness.latest_backup_available ? "Yes" : "No"}
                  tone={status.release_readiness.latest_backup_available ? "good" : "bad"}
                />
              </StatGrid>
            </div>

            <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-2">
              <Section title="Latest system check">
                <div className="mb-2 flex items-center gap-2">
                  <span
                    className={`text-sm font-semibold uppercase ${
                      STATUS_STYLES[status.latest_system_check.status] ?? "text-text-primary"
                    }`}
                  >
                    {status.latest_system_check.status}
                  </span>
                  <span className="text-xs text-text-muted">
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
                  <div className="text-xs text-text-secondary">
                    <p>
                      Run #{String(status.latest_market_workflow_run.id)} -{" "}
                      <span className="font-medium text-text-primary">
                        {String(status.latest_market_workflow_run.status)}
                      </span>
                    </p>
                    <p className="mt-1">
                      Started: {String(status.latest_market_workflow_run.started_at)}
                    </p>
                    {status.latest_market_workflow_run.error_message ? (
                      <p className="mt-1 text-signal-red">
                        {String(status.latest_market_workflow_run.error_message)}
                      </p>
                    ) : null}
                  </div>
                ) : (
                  <p className="text-xs text-text-muted">No workflow runs yet.</p>
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
                  <div className="text-xs text-text-secondary">
                    <p className="mono text-text-primary">
                      {String(status.latest_backup.filename)}
                    </p>
                    <p className="mt-1">
                      {String(status.latest_backup.size_bytes)} bytes - created{" "}
                      {String(status.latest_backup.created_at)}
                    </p>
                  </div>
                ) : (
                  <p className="text-xs text-text-muted">No backups found.</p>
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
                  <div className="text-xs text-text-secondary">
                    <p className="font-medium text-signal-red">{status.latest_error.message}</p>
                    <p className="mt-1">
                      {status.latest_error.level} - {status.latest_error.service} -{" "}
                      {status.latest_error.created_at}
                    </p>
                  </div>
                ) : (
                  <p className="text-xs text-text-muted">No errors recorded.</p>
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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="panel p-4">
      <h2 className="mb-2 text-sm font-semibold text-text-primary">{title}</h2>
      {children}
    </div>
  );
}
