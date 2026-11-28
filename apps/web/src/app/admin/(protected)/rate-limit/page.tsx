"use client";

import { useEffect, useState } from "react";

import { AdminSessionExpired } from "@/components/AdminSessionExpired";
import { AppHeader } from "@/components/AppHeader";
import { ErrorState, LoadingState } from "@/components/StateBlocks";
import { VersionFooter } from "@/components/VersionFooter";
import { ActionButton } from "@/components/ui/ActionButton";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  AdminAuthRequiredError,
  AdminNetworkError,
  AdminNotFoundError,
  AdminProxyError,
  AdminTimeoutError,
  type RateLimitStatus,
  fetchRateLimitStatus,
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

const COUNTERS: ReadonlyArray<[keyof RateLimitStatus, string]> = [
  ["platform_header_requests", "Platform header requests"],
  ["unverified_requests", "Unverified requests"],
  ["mismatch_requests", "Mismatch requests"],
];

function formatMyt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const text = date.toLocaleString("en-GB", {
    timeZone: "Asia/Kuala_Lumpur",
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  return `${text} MYT`;
}

export default function RateLimitPage() {
  const [data, setData] = useState<RateLimitStatus | null>(null);
  const [status, setStatus] = useState<PageStatus>("loading");
  const [proxyMessage, setProxyMessage] = useState<string | null>(null);

  // Only settles state from the promise, so the mount effect sets no state synchronously.
  function fetchAndApply() {
    fetchRateLimitStatus()
      .then((result) => {
        setData(result);
        setStatus("ready");
      })
      .catch((err) => {
        if (err instanceof AdminAuthRequiredError) setStatus("unauthorized");
        else if (err instanceof AdminNotFoundError) setStatus("not_found");
        else if (err instanceof AdminTimeoutError) setStatus("timeout");
        else if (err instanceof AdminNetworkError) setStatus("network_error");
        else if (err instanceof AdminProxyError) {
          setProxyMessage(err.message);
          setStatus("proxy_error");
        } else setStatus("error");
      });
  }

  function refresh() {
    setStatus("loading");
    fetchAndApply();
  }

  useEffect(() => {
    fetchAndApply();
  }, []);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <PageHeader title="Rate Limits" description="Status counts from the API's request limiter." />

        {status === "unauthorized" && <AdminSessionExpired />}

        {status === "loading" && <LoadingState>Loading rate-limit status…</LoadingState>}

        {status === "not_found" && (
          <ErrorState>The rate-limit status endpoint was not found (404). Is the backend up to date?</ErrorState>
        )}

        {status === "timeout" && (
          <ErrorState>Timed out waiting for rate-limit status (15s). Is the backend running and reachable?</ErrorState>
        )}

        {status === "network_error" && (
          <ErrorState>Could not reach the API proxy. Check that the web and api services are both running.</ErrorState>
        )}

        {status === "proxy_error" && <ErrorState>{proxyMessage ?? "The API proxy returned an error."}</ErrorState>}

        {status === "error" && <ErrorState>Failed to load rate-limit status. Is the backend running?</ErrorState>}

        {status === "ready" && data && (
          <>
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <ActionButton onClick={refresh}>Refresh</ActionButton>
              <span className="text-xs text-text-secondary">
                Limiter {data.enabled ? "enabled" : "disabled"}
              </span>
            </div>

            <div className="mb-4 rounded-control border border-signal-warning/40 bg-signal-warning/10 px-3 py-2 text-xs text-signal-warning">
              Counting since <span className="mono">{formatMyt(data.started_at)}</span> ({data.started_at}).
              Counts are per API process and reset on every deploy or restart.
            </div>

            <dl className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
              {COUNTERS.map(([key, label]) => (
                <div key={key} className="rounded-control border border-border-default px-3 py-2">
                  <dt className="text-xs text-text-secondary">{label}</dt>
                  <dd className="mono text-lg" data-testid={`count-${key}`}>
                    {String(data[key])}
                  </dd>
                </div>
              ))}
            </dl>

            <DataTableShell isEmpty={data.windows.length === 0} emptyLabel="No limiter windows configured.">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Group</th>
                    <th>Limit</th>
                    <th>Window (seconds)</th>
                    <th>Active keys</th>
                  </tr>
                </thead>
                <tbody>
                  {data.windows.map((window) => (
                    <tr key={window.group}>
                      <td className="mono text-text-secondary">{window.group}</td>
                      <td className="mono text-text-secondary">{window.limit}</td>
                      <td className="mono text-text-secondary">{window.window_seconds}</td>
                      <td className="mono text-text-secondary">{window.active_keys}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </DataTableShell>
          </>
        )}
      </main>
      <VersionFooter />
    </div>
  );
}
