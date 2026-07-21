"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { SeverityBadge } from "@/components/SeverityBadge";
import { VersionFooter } from "@/components/VersionFooter";
import {
  AdminAuthRequiredError,
  AdminNetworkError,
  AdminNotFoundError,
  AdminProxyError,
  AdminTimeoutError,
  type SystemCheckResponse,
  fetchSystemCheck,
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
  fail: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
};

export default function SystemCheckPage() {
  const [report, setReport] = useState<SystemCheckResponse | null>(null);
  const [status, setStatus] = useState<PageStatus>("loading");
  const [proxyError, setProxyError] = useState<ProxyErrorDetails | null>(null);

  function load() {
    setStatus("loading");
    fetchSystemCheck()
      .then((data) => {
        setReport(data);
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

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <div className="mb-4 flex items-baseline justify-between">
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-semibold text-neutral-100">System check</h1>
            <Link
              href="/admin/logs"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              App logs
            </Link>
            <Link
              href="/admin/release-status"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Release status
            </Link>
            <Link
              href="/admin/catalog-coverage"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Catalog coverage
            </Link>
            <Link
              href="/admin/source-mapping-quality"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Source mapping quality
            </Link>
            <Link
              href="/admin/card-duplicates"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Card duplicates
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
          A read-only consistency sweep across the database, backup coverage, and cross-table
          references.
        </p>

        {status === "unauthorized" && (
          <AdminAuthGate onTokenSaved={() => window.location.reload()} />
        )}

        {status === "loading" && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            Running system check…
          </div>
        )}

        {status === "not_found" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            The system-check endpoint was not found (404). Is the backend up to date?
          </div>
        )}

        {status === "timeout" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Timed out waiting for the system check (15s). Is the backend running and reachable?
          </div>
        )}

        {status === "network_error" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Could not reach the API proxy. Check that the web and api containers are both
            running.
          </div>
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
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Failed to run the system check. Is the backend running?
          </div>
        )}

        {status === "ready" && report && (
          <>
            <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
              <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
                <div className="text-xs uppercase tracking-wide text-neutral-500">
                  Overall status
                </div>
                <div
                  className={`mt-1 text-2xl font-semibold uppercase ${
                    STATUS_STYLES[report.status] ?? "text-neutral-100"
                  }`}
                >
                  {report.status}
                </div>
              </div>
              <StatCard label="Checks total" value={report.summary.checks_total} />
              <StatCard label="Passed" value={report.summary.checks_passed} tone="pass" />
              <StatCard label="Warnings" value={report.summary.warnings} tone="warning" />
              <StatCard label="Critical" value={report.summary.critical} tone="critical" />
            </div>

            <div className="overflow-x-auto rounded-lg border border-neutral-800">
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                    <th className="px-3 py-2 font-medium">Check</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2 font-medium">Severity</th>
                    <th className="px-3 py-2 font-medium">Message</th>
                  </tr>
                </thead>
                <tbody>
                  {report.checks.map((check) => (
                    <tr
                      key={check.name}
                      className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                    >
                      <td className="px-3 py-2 font-mono text-neutral-300">{check.name}</td>
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
                  ))}
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
