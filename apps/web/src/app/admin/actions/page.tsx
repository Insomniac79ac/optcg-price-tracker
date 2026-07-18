"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { VersionFooter } from "@/components/VersionFooter";
import {
  ADMIN_ACTION_SOURCES,
  AdminAuthRequiredError,
  getAdminToken,
  triggerFullMarketRefresh,
  triggerGenerateMarketReport,
  triggerRefreshPrices,
  triggerRunMarketWorkflow,
  triggerSendMarketReportDigest,
  triggerSnapshotMarketSignals,
  triggerSnapshotPortfolio,
} from "@/lib/api";

type ActionKey =
  | "refresh-prices"
  | "snapshot-portfolio"
  | "snapshot-market-signals"
  | "generate-market-report"
  | "full-market-refresh"
  | "send-market-report-digest"
  | "run-market-workflow";

const ACTION_LABELS: Record<ActionKey, string> = {
  "refresh-prices": "Refresh prices",
  "snapshot-portfolio": "Portfolio snapshot",
  "snapshot-market-signals": "Market signal snapshot",
  "generate-market-report": "Generate market report",
  "full-market-refresh": "Full market refresh",
  "send-market-report-digest": "Send market report digest",
  "run-market-workflow": "Run scheduled market workflow manually",
};

interface ActionResult {
  action: ActionKey;
  success: boolean;
  data?: unknown;
  error?: string;
}

function summarizeResult(action: ActionKey, data: unknown): { label: string; value: string }[] {
  if (!data || typeof data !== "object") return [];
  const d = data as Record<string, unknown>;

  switch (action) {
    case "refresh-prices":
      return [
        { label: "Run ID", value: d.run_id != null ? String(d.run_id) : "not available" },
        { label: "Job ID", value: d.job_id ? String(d.job_id) : "not available" },
        { label: "Status", value: d.status ? String(d.status) : "not available" },
      ];
    case "snapshot-portfolio":
      return [{ label: "Snapshot ID", value: String(d.snapshot_id) }];
    case "snapshot-market-signals":
      return [
        { label: "Created", value: String(d.created_count ?? 0) },
        { label: "Updated", value: String(d.updated_count ?? 0) },
        { label: "Resolved", value: String(d.resolved_count ?? 0) },
      ];
    case "generate-market-report":
      return [{ label: "Report ID", value: String(d.report_id) }];
    case "full-market-refresh": {
      const signals = (d.market_signal_snapshot ?? {}) as Record<string, unknown>;
      return [
        {
          label: "Price refresh run ID",
          value: d.price_refresh_run_id != null ? String(d.price_refresh_run_id) : "not available",
        },
        {
          label: "Portfolio snapshot ID",
          value: d.portfolio_snapshot_id != null ? String(d.portfolio_snapshot_id) : "not available",
        },
        { label: "Signals created", value: String(signals.created ?? 0) },
        { label: "Signals updated", value: String(signals.updated ?? 0) },
        { label: "Signals resolved", value: String(signals.resolved ?? 0) },
        {
          label: "Market report ID",
          value: d.market_report_id != null ? String(d.market_report_id) : "not available",
        },
        { label: "Dry run", value: d.dry_run ? "yes" : "no" },
      ];
    }
    case "send-market-report-digest":
      return [
        { label: "Report ID", value: d.report_id != null ? String(d.report_id) : "not available" },
        { label: "Status", value: d.status ? String(d.status) : "not available" },
        { label: "Sent", value: d.sent ? "yes" : "no" },
        {
          label: "Skipped reason",
          value: d.skipped_reason ? String(d.skipped_reason) : "not available",
        },
      ];
    case "run-market-workflow": {
      const signals = (d.market_signal_snapshot ?? {}) as Record<string, unknown>;
      return [
        {
          label: "Workflow run ID",
          value: d.market_workflow_run_id != null ? String(d.market_workflow_run_id) : "not available",
        },
        { label: "Status", value: d.status ? String(d.status) : "not available" },
        {
          label: "Price refresh run ID",
          value: d.price_refresh_run_id != null ? String(d.price_refresh_run_id) : "not available",
        },
        {
          label: "Portfolio snapshot ID",
          value: d.portfolio_snapshot_id != null ? String(d.portfolio_snapshot_id) : "not available",
        },
        { label: "Signals created", value: String(signals.created ?? 0) },
        { label: "Signals updated", value: String(signals.updated ?? 0) },
        { label: "Signals resolved", value: String(signals.resolved ?? 0) },
        {
          label: "Market report ID",
          value: d.market_report_id != null ? String(d.market_report_id) : "not available",
        },
        {
          label: "Telegram digest status",
          value: d.telegram_digest_status ? String(d.telegram_digest_status) : "not available",
        },
      ];
    }
    default:
      return [];
  }
}

function warningsOf(data: unknown): string[] {
  if (!data || typeof data !== "object") return [];
  const warnings = (data as Record<string, unknown>).warnings;
  return Array.isArray(warnings) ? warnings.filter((w): w is string => typeof w === "string") : [];
}

function messagePreviewOf(action: ActionKey, data: unknown): string | null {
  if (action !== "send-market-report-digest" || !data || typeof data !== "object") return null;
  const preview = (data as Record<string, unknown>).message_preview;
  return typeof preview === "string" ? preview : null;
}

export default function AdminActionsPage() {
  const [unauthorized, setUnauthorized] = useState(false);
  const [pendingAction, setPendingAction] = useState<ActionKey | null>(null);
  const [result, setResult] = useState<ActionResult | null>(null);

  const [refreshSource, setRefreshSource] = useState<string>("all");
  const [refreshLimit, setRefreshLimit] = useState("");
  const [refreshDryRun, setRefreshDryRun] = useState(false);

  const [fullSource, setFullSource] = useState<string>("all");
  const [fullLimit, setFullLimit] = useState("");
  const [fullDryRun, setFullDryRun] = useState(false);

  const [digestDryRun, setDigestDryRun] = useState(false);
  const [digestForce, setDigestForce] = useState(false);

  const [workflowSource, setWorkflowSource] = useState<string>("yuyutei");
  const [workflowLimit, setWorkflowLimit] = useState("");
  const [workflowSendTelegram, setWorkflowSendTelegram] = useState(false);
  const [workflowDryRun, setWorkflowDryRun] = useState(false);

  useEffect(() => {
    setUnauthorized(!getAdminToken());
  }, []);

  async function runAction(action: ActionKey, fn: () => Promise<unknown>) {
    setPendingAction(action);
    setResult(null);
    try {
      const data = await fn();
      setResult({ action, success: true, data });
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) {
        setUnauthorized(true);
      } else {
        setResult({
          action,
          success: false,
          error: err instanceof Error ? err.message : "Request failed.",
        });
      }
    } finally {
      setPendingAction(null);
    }
  }

  const isBusy = pendingAction !== null;

  function parseLimit(value: string): number | null {
    const trimmed = value.trim();
    if (trimmed === "") return null;
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : null;
  }

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <div className="mb-1 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">Admin Actions</h1>
          <AdminLogoutButton />
        </div>
        <p className="mb-6 text-xs text-neutral-500">
          Trigger refreshes, snapshots, and report generation.
        </p>

        {unauthorized && (
          <AdminAuthGate onTokenSaved={() => setUnauthorized(false)} />
        )}

        {!unauthorized && (
          <>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <ActionCard title="Refresh prices">
                <div className="flex flex-col gap-2">
                  <FieldRow label="Source">
                    <select
                      value={refreshSource}
                      onChange={(e) => setRefreshSource(e.target.value)}
                      disabled={isBusy}
                      className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200 disabled:opacity-50"
                    >
                      {ADMIN_ACTION_SOURCES.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </FieldRow>
                  <FieldRow label="Limit">
                    <input
                      type="number"
                      min={1}
                      value={refreshLimit}
                      onChange={(e) => setRefreshLimit(e.target.value)}
                      disabled={isBusy}
                      placeholder="default 10"
                      className="w-28 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200 placeholder:text-neutral-600 disabled:opacity-50"
                    />
                  </FieldRow>
                  <label className="flex items-center gap-1.5 text-xs text-neutral-400">
                    <input
                      type="checkbox"
                      checked={refreshDryRun}
                      onChange={(e) => setRefreshDryRun(e.target.checked)}
                      disabled={isBusy}
                    />
                    Dry run
                  </label>
                </div>
                <ActionButton
                  disabled={isBusy}
                  pending={pendingAction === "refresh-prices"}
                  onClick={() =>
                    runAction("refresh-prices", () =>
                      triggerRefreshPrices({
                        source: refreshSource,
                        limit: parseLimit(refreshLimit),
                        dry_run: refreshDryRun,
                      }),
                    )
                  }
                >
                  Run price refresh
                </ActionButton>
              </ActionCard>

              <ActionCard title="Portfolio snapshot">
                <p className="text-xs text-neutral-500">
                  Create one portfolio valuation snapshot from current data.
                </p>
                <ActionButton
                  disabled={isBusy}
                  pending={pendingAction === "snapshot-portfolio"}
                  onClick={() => runAction("snapshot-portfolio", () => triggerSnapshotPortfolio())}
                >
                  Create portfolio snapshot
                </ActionButton>
              </ActionCard>

              <ActionCard title="Market signal snapshot">
                <p className="text-xs text-neutral-500">
                  Snapshot current market signals into persistent signal events.
                </p>
                <ActionButton
                  disabled={isBusy}
                  pending={pendingAction === "snapshot-market-signals"}
                  onClick={() =>
                    runAction("snapshot-market-signals", () => triggerSnapshotMarketSignals())
                  }
                >
                  Snapshot market signals
                </ActionButton>
              </ActionCard>

              <ActionCard title="Generate market report">
                <p className="text-xs text-neutral-500">
                  Generate and store one deterministic market intelligence report.
                </p>
                <ActionButton
                  disabled={isBusy}
                  pending={pendingAction === "generate-market-report"}
                  onClick={() =>
                    runAction("generate-market-report", () => triggerGenerateMarketReport())
                  }
                >
                  Generate report
                </ActionButton>
              </ActionCard>

              <ActionCard title="Full market refresh" className="md:col-span-2">
                <div className="flex flex-col gap-2">
                  <FieldRow label="Source">
                    <select
                      value={fullSource}
                      onChange={(e) => setFullSource(e.target.value)}
                      disabled={isBusy}
                      className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200 disabled:opacity-50"
                    >
                      {ADMIN_ACTION_SOURCES.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </FieldRow>
                  <FieldRow label="Limit">
                    <input
                      type="number"
                      min={1}
                      value={fullLimit}
                      onChange={(e) => setFullLimit(e.target.value)}
                      disabled={isBusy}
                      placeholder="default 10"
                      className="w-28 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200 placeholder:text-neutral-600 disabled:opacity-50"
                    />
                  </FieldRow>
                  <label className="flex items-center gap-1.5 text-xs text-neutral-400">
                    <input
                      type="checkbox"
                      checked={fullDryRun}
                      onChange={(e) => setFullDryRun(e.target.checked)}
                      disabled={isBusy}
                    />
                    Dry run
                  </label>
                  <p className="text-xs text-neutral-500">
                    Refreshes prices, then (unless dry run) snapshots the portfolio, snapshots
                    market signals, and generates a market report.
                  </p>
                </div>
                <ActionButton
                  disabled={isBusy}
                  pending={pendingAction === "full-market-refresh"}
                  onClick={() =>
                    runAction("full-market-refresh", () =>
                      triggerFullMarketRefresh({
                        source: fullSource,
                        limit: parseLimit(fullLimit),
                        dry_run: fullDryRun,
                      }),
                    )
                  }
                >
                  Run full market refresh
                </ActionButton>
              </ActionCard>

              <ActionCard title="Send market report digest" className="md:col-span-2">
                <div className="flex flex-col gap-2">
                  <label className="flex items-center gap-1.5 text-xs text-neutral-400">
                    <input
                      type="checkbox"
                      checked={digestDryRun}
                      onChange={(e) => setDigestDryRun(e.target.checked)}
                      disabled={isBusy}
                    />
                    Dry run
                  </label>
                  <label className="flex items-center gap-1.5 text-xs text-neutral-400">
                    <input
                      type="checkbox"
                      checked={digestForce}
                      onChange={(e) => setDigestForce(e.target.checked)}
                      disabled={isBusy}
                    />
                    Force (resend even if already sent)
                  </label>
                  <p className="text-xs text-neutral-500">
                    Sends a concise Telegram digest of the latest market intelligence report.
                    Skipped if Telegram is not configured or already sent for this report.
                  </p>
                </div>
                <ActionButton
                  disabled={isBusy}
                  pending={pendingAction === "send-market-report-digest"}
                  onClick={() =>
                    runAction("send-market-report-digest", () =>
                      triggerSendMarketReportDigest({
                        dry_run: digestDryRun,
                        force: digestForce,
                      }),
                    )
                  }
                >
                  Send Telegram digest
                </ActionButton>
              </ActionCard>

              <ActionCard title="Run scheduled market workflow manually" className="md:col-span-2">
                <div className="flex flex-col gap-2">
                  <FieldRow label="Source">
                    <select
                      value={workflowSource}
                      onChange={(e) => setWorkflowSource(e.target.value)}
                      disabled={isBusy}
                      className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200 disabled:opacity-50"
                    >
                      {ADMIN_ACTION_SOURCES.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </FieldRow>
                  <FieldRow label="Limit">
                    <input
                      type="number"
                      min={1}
                      value={workflowLimit}
                      onChange={(e) => setWorkflowLimit(e.target.value)}
                      disabled={isBusy}
                      placeholder="default 10"
                      className="w-28 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200 placeholder:text-neutral-600 disabled:opacity-50"
                    />
                  </FieldRow>
                  <label className="flex items-center gap-1.5 text-xs text-neutral-400">
                    <input
                      type="checkbox"
                      checked={workflowSendTelegram}
                      onChange={(e) => setWorkflowSendTelegram(e.target.checked)}
                      disabled={isBusy}
                    />
                    Send Telegram digest
                  </label>
                  <label className="flex items-center gap-1.5 text-xs text-neutral-400">
                    <input
                      type="checkbox"
                      checked={workflowDryRun}
                      onChange={(e) => setWorkflowDryRun(e.target.checked)}
                      disabled={isBusy}
                    />
                    Dry run
                  </label>
                  <p className="text-xs text-neutral-500">
                    Runs the same sequence as the scheduled daily workflow: refresh prices,
                    snapshot the portfolio and market signals, generate a report, and
                    optionally send a Telegram digest. Recorded as a market workflow run.
                  </p>
                </div>
                <ActionButton
                  disabled={isBusy}
                  pending={pendingAction === "run-market-workflow"}
                  onClick={() =>
                    runAction("run-market-workflow", () =>
                      triggerRunMarketWorkflow({
                        source: workflowSource,
                        limit: parseLimit(workflowLimit),
                        send_telegram: workflowSendTelegram,
                        dry_run: workflowDryRun,
                      }),
                    )
                  }
                >
                  Run market workflow
                </ActionButton>
              </ActionCard>
            </div>

            {result && <ResultPanel result={result} />}

            <div className="mt-8 flex flex-wrap gap-3 text-xs">
              <Link
                href="/admin/refresh-runs"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Refresh runs
              </Link>
              <Link
                href="/admin/market-workflow-runs"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Market workflow runs
              </Link>
              <Link
                href="/admin/backup"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Backup &amp; restore
              </Link>
              <Link
                href="/admin/system-check"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                System check
              </Link>
              <Link
                href="/admin/release-status"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Release status
              </Link>
              <Link
                href="/admin/logs"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                App logs
              </Link>
              <Link
                href="/admin/data-retention"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Data retention
              </Link>
              <Link
                href="/collection"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Collection
              </Link>
              <Link
                href="/market/signals"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Market signals
              </Link>
              <Link
                href="/market/signal-events"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Signal events
              </Link>
              <Link
                href="/market/opportunities"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Opportunities
              </Link>
              <Link
                href="/market/report"
                className="text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
              >
                Market report
              </Link>
            </div>
          </>
        )}
        <VersionFooter />
      </main>
    </div>
  );
}

function ActionCard({
  title,
  children,
  className = "",
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col gap-3 rounded-lg border border-neutral-800 bg-neutral-900 p-4 ${className}`}
    >
      <h2 className="text-sm font-semibold text-neutral-200">{title}</h2>
      {children}
    </div>
  );
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex items-center gap-2 text-xs text-neutral-500">
      <span className="w-12 shrink-0">{label}</span>
      {children}
    </label>
  );
}

function ActionButton({
  children,
  onClick,
  disabled,
  pending,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled: boolean;
  pending: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="mt-1 self-start rounded bg-neutral-100 px-3 py-1.5 text-xs font-medium text-neutral-900 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
    >
      {pending ? "Running…" : children}
    </button>
  );
}

function ResultPanel({ result }: { result: ActionResult }) {
  const warnings = result.success ? warningsOf(result.data) : [];
  const summary = result.success ? summarizeResult(result.action, result.data) : [];
  const messagePreview = result.success ? messagePreviewOf(result.action, result.data) : null;

  return (
    <div className="mt-6 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <div className="mb-2 flex items-center gap-2">
        <span
          className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${
            result.success
              ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30"
              : "bg-rose-500/15 text-rose-300 ring-rose-500/30"
          }`}
        >
          {result.success ? "Success" : "Failed"}
        </span>
        <span className="text-sm font-semibold text-neutral-200">
          {ACTION_LABELS[result.action]}
        </span>
      </div>

      {!result.success && (
        <p className="mb-2 text-sm text-rose-300">{result.error ?? "Request failed."}</p>
      )}

      {result.success && summary.length > 0 && (
        <div className="mb-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {summary.map((item) => (
            <div key={item.label} className="rounded border border-neutral-800 px-2 py-1.5">
              <div className="text-[11px] uppercase tracking-wide text-neutral-500">
                {item.label}
              </div>
              <div className="text-sm font-medium text-neutral-100">{item.value}</div>
            </div>
          ))}
        </div>
      )}

      {messagePreview && (
        <div className="mb-2 rounded border border-neutral-800 bg-neutral-950 p-3">
          <div className="mb-1 text-[11px] uppercase tracking-wide text-neutral-500">
            Message preview
          </div>
          <pre className="whitespace-pre-wrap text-xs text-neutral-300">{messagePreview}</pre>
        </div>
      )}

      {warnings.length > 0 && (
        <ul className="mb-2 list-disc space-y-1 rounded border border-amber-900/50 bg-amber-950/20 p-3 pl-8 text-xs text-amber-200">
          {warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}

      {result.success && (
        <details className="text-xs text-neutral-500">
          <summary className="cursor-pointer select-none hover:text-neutral-300">
            Raw JSON
          </summary>
          <pre className="mt-2 max-h-64 overflow-auto rounded bg-neutral-950 p-3 text-[11px] text-neutral-400">
            {JSON.stringify(result.data, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
