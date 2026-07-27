"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AdminSessionExpired } from "@/components/AdminSessionExpired";
import { AppHeader } from "@/components/AppHeader";
import { SeverityBadge } from "@/components/SeverityBadge";
import { ErrorState, LoadingState } from "@/components/StateBlocks";
import { DataTableShell } from "@/components/ui/DataTableShell";
import { FILTER_INPUT_CLASS } from "@/components/ui/FilterBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatCard, StatGrid } from "@/components/ui/StatCard";
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
        <PageHeader title="Card catalog audit" />
        <div className="mb-4 flex flex-wrap gap-3 text-xs text-text-muted">
          <Link href="/admin/cards" className="text-sky-400 hover:underline">
            Card catalog (import/export)
          </Link>
          <Link href="/admin/catalog-coverage" className="text-sky-400 hover:underline">
            Catalog coverage
          </Link>
          <Link href="/admin/price-source-health" className="text-sky-400 hover:underline">
            Price source health
          </Link>
          <Link href="/admin/source-mapping-quality" className="text-sky-400 hover:underline">
            Source mapping quality
          </Link>
          <Link href="/admin/card-duplicates" className="text-sky-400 hover:underline">
            Card duplicates
          </Link>
          <Link href="/admin/import-validation" className="text-sky-400 hover:underline">
            Import validation
          </Link>
          <Link href="/admin/catalog-ops" className="text-sky-400 hover:underline">
            Catalog operations
          </Link>
        </div>

        {status === "unauthorized" && (
          <AdminSessionExpired />
        )}

        {status === "loading" && <LoadingState>Loading catalog audit…</LoadingState>}

        {status === "not_found" && (
          <ErrorState>
            The card audit endpoint was not found (404). Is the backend up to date?
          </ErrorState>
        )}

        {status === "timeout" && (
          <ErrorState>
            Timed out waiting for the catalog audit (15s). Is the backend running and reachable?
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

        {status === "no_data" && <ErrorState>No data received from API</ErrorState>}

        {status === "error" && (
          <ErrorState>
            Failed to load the catalog audit from the API. Is the backend running?
          </ErrorState>
        )}

        {status === "ready" && report && (
          <>
            <StatGrid>
              <StatCard label="Total cards" value={report.summary.total_cards} />
              <StatCard label="Total issues" value={report.summary.total_issues} />
              <StatCard
                label="Critical"
                value={report.summary.critical_issues}
                tone={report.summary.critical_issues > 0 ? "bad" : "neutral"}
              />
              <StatCard
                label="Warning"
                value={report.summary.warning_issues}
                tone={report.summary.warning_issues > 0 ? "bad" : "neutral"}
              />
            </StatGrid>

            {report.issues.some((i) => i.issue_type === "duplicate_card_identity") && (
              <div className="mb-4 mt-4 rounded-control border border-signal-warning/40 bg-signal-warning/10 px-4 py-3 text-sm text-signal-warning">
                Duplicate card identity issues found — consider{" "}
                <Link href="/admin/import-validation" className="underline hover:no-underline">
                  validating catalog imports
                </Link>{" "}
                before importing more cards.
              </div>
            )}

            <div className="mb-4 mt-4 flex flex-wrap items-center gap-2">
              <div className="flex gap-1">
                {SEVERITY_FILTERS.map((f) => (
                  <button
                    key={f.value}
                    type="button"
                    onClick={() => setSeverityFilter(f.value)}
                    className={`rounded-control px-2.5 py-1 text-xs font-medium ring-1 ring-inset transition-colors ${
                      severityFilter === f.value
                        ? "bg-accent-gold text-black/80 ring-accent-gold"
                        : "bg-bg-surface text-text-secondary ring-border-default hover:text-text-primary"
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              <select
                value={issueTypeFilter}
                onChange={(e) => setIssueTypeFilter(e.target.value)}
                className={FILTER_INPUT_CLASS}
              >
                {issueTypeOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <span className="ml-auto text-sm text-text-muted">
                {filteredIssues.length} of {report.issues.length} issue
                {report.issues.length === 1 ? "" : "s"}
              </span>
            </div>

            <DataTableShell isEmpty={filteredIssues.length === 0} emptyLabel="No catalog issues found">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Issue type</th>
                    <th>Card code</th>
                    <th>Card IDs</th>
                    <th>Message</th>
                    <th>Suggested action</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredIssues.map((issue, idx) => (
                    <tr key={`${issue.issue_type}-${idx}`}>
                      <td>
                        <SeverityBadge severity={issue.severity} />
                      </td>
                      <td className="mono text-text-secondary">{issue.issue_type}</td>
                      <td className="mono text-text-secondary">{issue.card_code ?? "—"}</td>
                      <td className="max-w-xs">
                        <CardIdsCell cardIds={issue.card_ids} />
                      </td>
                      <td className="max-w-md">
                        <span className="block text-text-secondary" title={issue.message}>
                          {issue.message}
                        </span>
                      </td>
                      <td className="text-xs text-text-muted">{issue.suggested_action}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </DataTableShell>
          </>
        )}
      </main>
    </div>
  );
}

function CardIdsCell({ cardIds }: { cardIds: number[] }) {
  if (cardIds.length === 0) {
    return <span className="text-text-faint">—</span>;
  }

  const shown = cardIds.slice(0, 6);
  const remaining = cardIds.length - shown.length;

  return (
    <div className="flex flex-wrap gap-1 text-xs">
      {shown.map((id) => (
        <Link
          key={id}
          href={`/cards/${id}`}
          className="mono rounded-control bg-bg-elevated px-1.5 py-0.5 text-text-secondary hover:text-sky-400"
        >
          {id}
        </Link>
      ))}
      {remaining > 0 && <span className="px-1.5 py-0.5 text-text-muted">+{remaining} more</span>}
    </div>
  );
}
