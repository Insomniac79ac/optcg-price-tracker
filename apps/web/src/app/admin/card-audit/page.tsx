"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { SeverityBadge } from "@/components/SeverityBadge";
import {
  AdminAuthRequiredError,
  AdminInvalidResponseError,
  AdminNetworkError,
  AdminNotFoundError,
  AdminProxyError,
  AdminTimeoutError,
  type CardAuditReport,
  fetchCardAudit,
} from "@/lib/api";

const SEVERITY_FILTERS = [
  { value: "", label: "All" },
  { value: "critical", label: "Critical" },
  { value: "warning", label: "Warning" },
];

type PageStatus =
  | "loading"
  | "ready"
  | "unauthorized"
  | "not_found"
  | "timeout"
  | "network_error"
  | "proxy_error"
  | "no_data"
  | "error";

interface ProxyErrorDetails {
  message: string;
  backendStatus?: number;
  bodyPreview?: string;
}

export default function CardAuditPage() {
  const [report, setReport] = useState<CardAuditReport | null>(null);
  const [status, setStatus] = useState<PageStatus>("loading");
  const [proxyError, setProxyError] = useState<ProxyErrorDetails | null>(null);
  const [severityFilter, setSeverityFilter] = useState("");
  const [issueTypeFilter, setIssueTypeFilter] = useState("");

  useEffect(() => {
    let cancelled = false;
    let succeeded = false;

    fetchCardAudit()
      .then((data) => {
        if (cancelled) return;
        setReport(data);
        succeeded = true;
      })
      .catch((err) => {
        if (cancelled) return;
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
        } else if (err instanceof AdminInvalidResponseError)
          setStatus("no_data");
        else setStatus("error");
      })
      .finally(() => {
        // Always clear the loading state - success sets "ready" here rather
        // than in .then() so a request that never resolves or rejects can't
        // leave the page stuck on "Loading catalog audit…" forever.
        if (cancelled) return;
        if (succeeded) setStatus("ready");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const issueTypeOptions = useMemo(() => {
    const values = Array.from(
      new Set((report?.issues ?? []).map((i) => i.issue_type)),
    ).sort();
    return [
      { value: "", label: "All issue types" },
      ...values.map((v) => ({ value: v, label: v })),
    ];
  }, [report]);

  const filteredIssues = useMemo(() => {
    if (!report) return [];
    return report.issues.filter(
      (issue) =>
        (!severityFilter || issue.severity === severityFilter) &&
        (!issueTypeFilter || issue.issue_type === issueTypeFilter),
    );
  }, [report, severityFilter, issueTypeFilter]);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-4 flex items-baseline justify-between">
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-semibold text-neutral-100">
              Card catalog audit
            </h1>
            <Link
              href="/admin/cards"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Card catalog (import/export) →
            </Link>
          </div>
          <AdminLogoutButton />
        </div>

        {status === "unauthorized" && (
          <AdminAuthGate onTokenSaved={() => window.location.reload()} />
        )}

        {status === "loading" && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            Loading catalog audit…
          </div>
        )}

        {status === "not_found" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            The card audit endpoint was not found (404). Is the backend up to
            date?
          </div>
        )}

        {status === "timeout" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Timed out waiting for the catalog audit (15s). Is the backend
            running and reachable?
          </div>
        )}

        {status === "network_error" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Could not reach the API proxy. Check that the web and api
            containers are both running.
          </div>
        )}

        {status === "proxy_error" && proxyError && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-6 text-sm text-rose-300">
            <p className="font-medium">{proxyError.message}</p>
            {proxyError.backendStatus !== undefined && (
              <p className="mt-1 text-rose-400">
                backend_status: {proxyError.backendStatus}
              </p>
            )}
            {proxyError.bodyPreview && (
              <pre className="mt-3 max-h-48 overflow-auto rounded border border-rose-900/50 bg-rose-950/40 p-3 text-xs whitespace-pre-wrap text-rose-200">
                {proxyError.bodyPreview}
              </pre>
            )}
          </div>
        )}

        {status === "no_data" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            No data received from API
          </div>
        )}

        {status === "error" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Failed to load the catalog audit from the API. Is the backend
            running?
          </div>
        )}

        {status === "ready" && report && (
          <>
            <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatCard label="Total cards" value={report.summary.total_cards} />
              <StatCard
                label="Total issues"
                value={report.summary.total_issues}
              />
              <StatCard
                label="Critical"
                value={report.summary.critical_issues}
                tone="critical"
              />
              <StatCard
                label="Warning"
                value={report.summary.warning_issues}
                tone="warning"
              />
            </div>

            <div className="mb-4 flex flex-wrap items-center gap-2">
              <div className="flex gap-1">
                {SEVERITY_FILTERS.map((f) => (
                  <button
                    key={f.value}
                    onClick={() => setSeverityFilter(f.value)}
                    className={`rounded px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                      severityFilter === f.value
                        ? "bg-neutral-100 text-neutral-900 ring-neutral-100"
                        : "bg-neutral-900 text-neutral-400 ring-neutral-800 hover:text-neutral-100"
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              <select
                value={issueTypeFilter}
                onChange={(e) => setIssueTypeFilter(e.target.value)}
                className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
              >
                {issueTypeOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <span className="ml-auto text-sm text-neutral-500">
                {filteredIssues.length} of {report.issues.length} issue
                {report.issues.length === 1 ? "" : "s"}
              </span>
            </div>

            {filteredIssues.length === 0 && (
              <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
                No catalog issues found
              </div>
            )}

            {filteredIssues.length > 0 && (
              <div className="overflow-x-auto rounded-lg border border-neutral-800">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wide text-neutral-500">
                      <th className="px-3 py-2 font-medium">Severity</th>
                      <th className="px-3 py-2 font-medium">Issue type</th>
                      <th className="px-3 py-2 font-medium">Card code</th>
                      <th className="px-3 py-2 font-medium">Card IDs</th>
                      <th className="px-3 py-2 font-medium">Message</th>
                      <th className="px-3 py-2 font-medium">
                        Suggested action
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredIssues.map((issue, idx) => (
                      <tr
                        key={`${issue.issue_type}-${idx}`}
                        className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                      >
                        <td className="px-3 py-2">
                          <SeverityBadge severity={issue.severity} />
                        </td>
                        <td className="px-3 py-2 font-mono text-xs text-neutral-300">
                          {issue.issue_type}
                        </td>
                        <td className="px-3 py-2 font-mono text-xs text-neutral-400">
                          {issue.card_code ?? "—"}
                        </td>
                        <td className="max-w-xs px-3 py-2">
                          <CardIdsCell cardIds={issue.card_ids} />
                        </td>
                        <td className="max-w-md px-3 py-2">
                          <span
                            className="block text-neutral-300"
                            title={issue.message}
                          >
                            {issue.message}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-xs text-neutral-500">
                          {issue.suggested_action}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
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
  tone?: "critical" | "warning";
}) {
  const toneClass =
    tone === "critical"
      ? "text-rose-300"
      : tone === "warning"
        ? "text-amber-300"
        : "text-neutral-100";

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">
        {label}
      </div>
      <div className={`mt-1 text-2xl font-semibold ${toneClass}`}>
        {value}
      </div>
    </div>
  );
}

function CardIdsCell({ cardIds }: { cardIds: number[] }) {
  if (cardIds.length === 0) {
    return <span className="text-neutral-600">—</span>;
  }

  const shown = cardIds.slice(0, 6);
  const remaining = cardIds.length - shown.length;

  return (
    <div className="flex flex-wrap gap-1 text-xs">
      {shown.map((id) => (
        <Link
          key={id}
          href={`/cards/${id}`}
          className="rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-neutral-300 hover:text-sky-400"
        >
          {id}
        </Link>
      ))}
      {remaining > 0 && (
        <span className="px-1.5 py-0.5 text-neutral-500">
          +{remaining} more
        </span>
      )}
    </div>
  );
}
