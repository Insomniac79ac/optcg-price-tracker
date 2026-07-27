"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminSessionExpired } from "@/components/AdminSessionExpired";
import { AppHeader } from "@/components/AppHeader";
import { SeverityBadge } from "@/components/SeverityBadge";
import { ErrorState, LoadingState } from "@/components/StateBlocks";
import { VersionFooter } from "@/components/VersionFooter";
import { ActionButton } from "@/components/ui/ActionButton";
import { Badge } from "@/components/ui/Badge";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatCard, StatGrid } from "@/components/ui/StatCard";
import {
  AdminAuthRequiredError,
  AdminNetworkError,
  AdminNotFoundError,
  AdminProxyError,
  AdminTimeoutError,
  type DbIndexAuditResponse,
  type PerformanceSummary,
  fetchDbIndexAudit,
  fetchPerformanceSummary,
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

const DEFAULT_STATUS_STYLE = "bg-neutral-500/15 text-neutral-300 ring-1 ring-inset ring-neutral-500/30";

const STATUS_STYLES: Record<string, string> = {
  ok: "bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/30",
  warning: "bg-amber-500/15 text-amber-300 ring-1 ring-inset ring-amber-500/30",
  critical: "bg-rose-500/15 text-rose-300 ring-1 ring-inset ring-rose-500/30",
};

const CHECK_STATUS_STYLES: Record<string, string> = {
  pass: "bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/30",
  warning: "bg-amber-500/15 text-amber-300 ring-1 ring-inset ring-amber-500/30",
  critical: "bg-rose-500/15 text-rose-300 ring-1 ring-inset ring-rose-500/30",
};

export default function PerformancePage() {
  const [summary, setSummary] = useState<PerformanceSummary | null>(null);
  const [audit, setAudit] = useState<DbIndexAuditResponse | null>(null);
  const [status, setStatus] = useState<PageStatus>("loading");
  const [proxyError, setProxyError] = useState<ProxyErrorDetails | null>(null);

  function load() {
    setStatus("loading");
    Promise.all([fetchPerformanceSummary(), fetchDbIndexAudit()])
      .then(([summaryData, auditData]) => {
        setSummary(summaryData);
        setAudit(auditData);
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

  const checks = audit?.checks ?? [];

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <PageHeader
          title="Performance"
          description="Table growth, index coverage, and slow-request warnings - see docs/operations.md for how to act on a warning/critical result here."
          actions={
            <>
              <ActionButton onClick={load}>Re-run</ActionButton>
            </>
          }
        />
        <div className="mb-4 flex flex-wrap gap-3 text-xs text-text-muted">
          <Link href="/admin/logs" className="text-sky-400 hover:underline">
            App logs
          </Link>
          <Link href="/admin/system-check" className="text-sky-400 hover:underline">
            System check
          </Link>
          <Link href="/admin/data-retention" className="text-sky-400 hover:underline">
            Data retention
          </Link>
          <Link href="/admin/cache" className="text-sky-400 hover:underline">
            Cache
          </Link>
          <Link href="/admin/job-locks" className="text-sky-400 hover:underline">
            Job locks
          </Link>
          <Link href="/admin/file-jobs" className="text-sky-400 hover:underline">
            File jobs
          </Link>
          <Link href="/admin/release-status" className="text-sky-400 hover:underline">
            Release status
          </Link>
        </div>

        {status === "unauthorized" && (
          <AdminSessionExpired />
        )}

        {status === "loading" && <LoadingState>Loading performance summary…</LoadingState>}

        {status === "not_found" && (
          <ErrorState>
            The performance endpoint was not found (404). Is the backend up to date?
          </ErrorState>
        )}

        {status === "timeout" && (
          <ErrorState>
            Timed out waiting for the performance summary (15s). Is the backend running and
            reachable?
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
          <ErrorState>Failed to load the performance summary. Is the backend running?</ErrorState>
        )}

        {status === "ready" && summary && (
          <>
            <StatGrid>
              <StatCard
                label="Overall status"
                value={<Badge label={summary.status} className={`uppercase ${STATUS_STYLES[summary.status] ?? DEFAULT_STATUS_STYLE}`} />}
              />
              <StatCard label="Price observations" value={summary.database.price_observations_count} />
              <StatCard label="Raw snapshots" value={summary.database.raw_snapshots_count} />
              <StatCard label="Signal events" value={summary.database.market_signal_events_count} />
              <StatCard label="Activity events" value={summary.database.collector_activity_events_count} />
              <StatCard label="App logs" value={summary.database.app_log_events_count} />
              <StatCard
                label="Index warnings"
                value={summary.index_audit.warnings}
                tone={summary.index_audit.warnings > 0 ? "bad" : "neutral"}
              />
              <StatCard
                label="Index critical"
                value={summary.index_audit.critical}
                tone={summary.index_audit.critical > 0 ? "bad" : "neutral"}
              />
              <StatCard
                label="Response size warnings (24h)"
                value={summary.response_size_warnings_last_24h}
                tone={summary.response_size_warnings_last_24h > 0 ? "bad" : "neutral"}
              />
              <StatCard
                label="Slow requests (24h)"
                value={summary.slow_requests_last_24h}
                tone={summary.slow_requests_last_24h > 0 ? "bad" : "neutral"}
              />
              <StatCard
                label="Cache backend"
                value={summary.cache_enabled ? summary.cache_backend : "disabled"}
              />
              {summary.cache_keys !== null && <StatCard label="Cache keys" value={summary.cache_keys} />}
            </StatGrid>

            <h2 className="mb-2 mt-6 text-sm font-semibold text-text-primary">Index audit</h2>
            <div className="mb-6">
              <DataTableShell isEmpty={checks.length === 0} emptyLabel="No index checks available.">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Table</th>
                      <th>Index</th>
                      <th>Status</th>
                      <th>Severity</th>
                      <th>Message</th>
                    </tr>
                  </thead>
                  <tbody>
                    {checks.map((check) => (
                      <tr key={`${check.table}.${check.index}`}>
                        <td className="mono text-text-secondary">{check.table}</td>
                        <td className="mono text-text-secondary">{check.index}</td>
                        <td>
                          <Badge
                            label={check.status}
                            className={CHECK_STATUS_STYLES[check.status] ?? DEFAULT_STATUS_STYLE}
                          />
                        </td>
                        <td>
                          <SeverityBadge severity={check.severity} />
                        </td>
                        <td className="text-text-secondary">{check.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </DataTableShell>
            </div>

            <h2 className="mb-2 text-sm font-semibold text-text-primary">Latest slow requests</h2>
            <div className="mb-6">
              <DataTableShell
                isEmpty={summary.latest_slow_requests.length === 0}
                emptyLabel="No slow requests recorded."
              >
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Recorded at</th>
                      <th>Message</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.latest_slow_requests.map((req, i) => (
                      <tr key={`${req.created_at}-${i}`}>
                        <td className="mono whitespace-nowrap text-text-secondary">
                          {new Date(req.created_at).toLocaleString()}
                        </td>
                        <td className="text-text-secondary">{req.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </DataTableShell>
            </div>

            <div className="mb-2 flex items-baseline justify-between">
              <h2 className="text-sm font-semibold text-text-primary">Largest recent responses</h2>
              <Link href="/admin/logs?event_type=response_size_warning" className="text-xs text-sky-400 hover:underline">
                View in logs
              </Link>
            </div>
            <DataTableShell
              isEmpty={summary.largest_recent_responses.length === 0}
              emptyLabel="No response size warnings recorded."
            >
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Recorded at</th>
                    <th>Method</th>
                    <th>Path</th>
                    <th>Size</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.largest_recent_responses.map((res, i) => (
                    <tr key={`${res.created_at}-${i}`}>
                      <td className="mono whitespace-nowrap text-text-secondary">
                        {new Date(res.created_at).toLocaleString()}
                      </td>
                      <td className="text-text-secondary">{res.method ?? "-"}</td>
                      <td className="mono text-text-secondary">{res.path ?? "-"}</td>
                      <td className="text-text-secondary">
                        {res.size_bytes !== null ? `${(res.size_bytes / 1_000_000).toFixed(2)} MB` : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </DataTableShell>
          </>
        )}
        <VersionFooter />
      </main>
    </div>
  );
}
