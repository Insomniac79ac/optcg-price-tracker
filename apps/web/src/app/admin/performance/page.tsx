"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { SeverityBadge } from "@/components/SeverityBadge";
import { ErrorState, LoadingState } from "@/components/StateBlocks";
import { VersionFooter } from "@/components/VersionFooter";
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

const STATUS_STYLES: Record<string, string> = {
  ok: "text-emerald-400",
  warning: "text-amber-400",
  critical: "text-rose-400",
};

const CHECK_STATUS_STYLES: Record<string, string> = {
  pass: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  warning: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  critical: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
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
        <div className="mb-4 flex items-baseline justify-between">
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-semibold text-neutral-100">Performance</h1>
            <Link
              href="/admin/logs"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              App logs
            </Link>
            <Link
              href="/admin/system-check"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              System check
            </Link>
            <Link
              href="/admin/data-retention"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Data retention
            </Link>
            <Link
              href="/admin/release-status"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Release status
            </Link>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={load}
              className="rounded border border-neutral-700 px-3 py-1.5 text-xs font-medium text-neutral-200 hover:text-neutral-100"
            >
              Re-run
            </button>
            <AdminLogoutButton />
          </div>
        </div>
        <p className="mb-4 text-sm text-neutral-500">
          Table growth, index coverage, and slow-request warnings - see docs/operations.md
          for how to act on a warning/critical result here.
        </p>

        {status === "unauthorized" && (
          <AdminAuthGate onTokenSaved={() => window.location.reload()} />
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
          <ErrorState>Failed to load the performance summary. Is the backend running?</ErrorState>
        )}

        {status === "ready" && summary && (
          <>
            <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
                <div className="text-xs uppercase tracking-wide text-neutral-500">
                  Overall status
                </div>
                <div
                  className={`mt-1 text-2xl font-semibold uppercase ${
                    STATUS_STYLES[summary.status] ?? "text-neutral-100"
                  }`}
                >
                  {summary.status}
                </div>
              </div>
              <StatCard
                label="Price observations"
                value={summary.database.price_observations_count}
              />
              <StatCard label="Raw snapshots" value={summary.database.raw_snapshots_count} />
              <StatCard
                label="Signal events"
                value={summary.database.market_signal_events_count}
              />
              <StatCard
                label="Activity events"
                value={summary.database.collector_activity_events_count}
              />
              <StatCard label="App logs" value={summary.database.app_log_events_count} />
              <StatCard
                label="Index warnings"
                value={summary.index_audit.warnings}
                tone="warning"
              />
              <StatCard
                label="Index critical"
                value={summary.index_audit.critical}
                tone="critical"
              />
              <StatCard
                label="Response size warnings (24h)"
                value={summary.response_size_warnings_last_24h}
                tone="warning"
              />
              <StatCard
                label="Slow requests (24h)"
                value={summary.slow_requests_last_24h}
                tone="warning"
              />
            </div>

            <h2 className="mb-2 text-sm font-semibold text-neutral-200">Index audit</h2>
            <div className="mb-6 overflow-x-auto rounded-lg border border-neutral-800">
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                    <th className="px-3 py-2 font-medium">Table</th>
                    <th className="px-3 py-2 font-medium">Index</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2 font-medium">Severity</th>
                    <th className="px-3 py-2 font-medium">Message</th>
                  </tr>
                </thead>
                <tbody>
                  {checks.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-3 py-6 text-center text-neutral-500">
                        No index checks available.
                      </td>
                    </tr>
                  ) : (
                    checks.map((check) => (
                      <tr
                        key={`${check.table}.${check.index}`}
                        className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                      >
                        <td className="px-3 py-2 font-mono text-neutral-300">{check.table}</td>
                        <td className="px-3 py-2 font-mono text-neutral-300">{check.index}</td>
                        <td className="px-3 py-2">
                          <span
                            className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${
                              CHECK_STATUS_STYLES[check.status] ??
                              "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30"
                            }`}
                          >
                            {check.status}
                          </span>
                        </td>
                        <td className="px-3 py-2">
                          <SeverityBadge severity={check.severity} />
                        </td>
                        <td className="px-3 py-2 text-neutral-400">{check.message}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <h2 className="mb-2 text-sm font-semibold text-neutral-200">
              Latest slow requests
            </h2>
            <div className="mb-6 overflow-x-auto rounded-lg border border-neutral-800">
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                    <th className="px-3 py-2 font-medium">Recorded at</th>
                    <th className="px-3 py-2 font-medium">Message</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.latest_slow_requests.length === 0 ? (
                    <tr>
                      <td colSpan={2} className="px-3 py-6 text-center text-neutral-500">
                        No slow requests recorded.
                      </td>
                    </tr>
                  ) : (
                    summary.latest_slow_requests.map((req, i) => (
                      <tr
                        key={`${req.created_at}-${i}`}
                        className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                      >
                        <td className="whitespace-nowrap px-3 py-2 text-neutral-400">
                          {new Date(req.created_at).toLocaleString()}
                        </td>
                        <td className="px-3 py-2 text-neutral-300">{req.message}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <div className="mb-2 flex items-baseline justify-between">
              <h2 className="text-sm font-semibold text-neutral-200">
                Largest recent responses
              </h2>
              <Link
                href="/admin/logs?event_type=response_size_warning"
                className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                View in logs
              </Link>
            </div>
            <div className="overflow-x-auto rounded-lg border border-neutral-800">
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                    <th className="px-3 py-2 font-medium">Recorded at</th>
                    <th className="px-3 py-2 font-medium">Method</th>
                    <th className="px-3 py-2 font-medium">Path</th>
                    <th className="px-3 py-2 font-medium">Size</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.largest_recent_responses.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="px-3 py-6 text-center text-neutral-500">
                        No response size warnings recorded.
                      </td>
                    </tr>
                  ) : (
                    summary.largest_recent_responses.map((res, i) => (
                      <tr
                        key={`${res.created_at}-${i}`}
                        className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                      >
                        <td className="whitespace-nowrap px-3 py-2 text-neutral-400">
                          {new Date(res.created_at).toLocaleString()}
                        </td>
                        <td className="px-3 py-2 text-neutral-300">{res.method ?? "-"}</td>
                        <td className="px-3 py-2 font-mono text-neutral-300">
                          {res.path ?? "-"}
                        </td>
                        <td className="px-3 py-2 text-neutral-300">
                          {res.size_bytes !== null
                            ? `${(res.size_bytes / 1_000_000).toFixed(2)} MB`
                            : "-"}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
        <VersionFooter />
      </main>
    </div>
  );
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "pass" | "warning" | "critical";
}) {
  const toneClass =
    tone === "critical" && value > 0
      ? "text-rose-400"
      : tone === "warning" && value > 0
        ? "text-amber-400"
        : tone === "pass"
          ? "text-emerald-400"
          : "text-neutral-100";
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}
