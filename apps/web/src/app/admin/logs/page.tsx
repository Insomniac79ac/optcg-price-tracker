"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { LogLevelBadge } from "@/components/LogLevelBadge";
import { PaginationControls } from "@/components/PaginationControls";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import {
  AdminAuthRequiredError,
  APP_LOG_LEVELS,
  type AppLogEvent,
  type AppLogListResponse,
  type ObservabilitySummary,
  fetchAppLogs,
  fetchObservabilitySummary,
  pruneAppLogs,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";

const NA = "not available";
const ALL_OPTION = "";

const RELATED_ENTITY_LINKS: Record<string, string> = {
  market_workflow_run: "/admin/market-workflow-runs",
  price_refresh_run: "/admin/refresh-runs",
};

function naText(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return NA;
  return String(value);
}

export default function AdminLogsPage() {
  const [unauthorized, setUnauthorized] = useState(false);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [error, setError] = useState<string | null>(null);

  const [summary, setSummary] = useState<ObservabilitySummary | null>(null);
  const [data, setData] = useState<AppLogListResponse | null>(null);
  const [selectedLog, setSelectedLog] = useState<AppLogEvent | null>(null);

  const [level, setLevel] = useState(ALL_OPTION);
  const [service, setService] = useState(ALL_OPTION);
  const [eventType, setEventType] = useState(ALL_OPTION);
  const [q, setQ] = useState("");
  const [sinceHours, setSinceHours] = useState<string>("24");
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);

  const loadLogs = useCallback(async () => {
    setStatus("loading");
    setError(null);
    try {
      const result = await fetchAppLogs({
        level: level || undefined,
        service: service || undefined,
        event_type: eventType || undefined,
        q: q || undefined,
        since_hours: sinceHours ? Number(sinceHours) : undefined,
        limit,
        offset,
      });
      setData(result);
      setStatus("ready");
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) {
        setUnauthorized(true);
      } else {
        setError(err instanceof Error ? err.message : "Failed to load logs.");
        setStatus("error");
      }
    }
  }, [level, service, eventType, q, sinceHours, limit, offset]);

  // Any filter/page-size change re-pages to the start - an offset from the
  // old filter's result set is otherwise almost certainly out of range for
  // the new one.
  useEffect(() => {
    setOffset(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [level, service, eventType, q, sinceHours, limit]);

  const loadSummary = useCallback(async () => {
    try {
      const result = await fetchObservabilitySummary();
      setSummary(result);
    } catch (err) {
      if (err instanceof AdminAuthRequiredError) setUnauthorized(true);
    }
  }, []);

  useEffect(() => {
    setUnauthorized(false);
    loadLogs();
  }, [loadLogs]);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  const serviceOptions = data ? Object.keys(data.summary.by_service).sort() : [];
  const eventTypeOptions = data ? Object.keys(data.summary.by_event_type).sort() : [];

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-1 flex items-baseline justify-between">
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-semibold text-neutral-100">App logs</h1>
            <Link
              href="/admin/actions"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Admin actions
            </Link>
            <Link
              href="/admin/data-retention"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Data retention
            </Link>
          </div>
          <AdminLogoutButton />
        </div>
        <p className="mb-6 text-xs text-neutral-500">
          Recent app, worker, backup, import, and workflow events.
        </p>

        {unauthorized && (
          <AdminAuthGate
            onTokenSaved={() => {
              setUnauthorized(false);
              loadLogs();
              loadSummary();
            }}
          />
        )}

        {!unauthorized && (
          <div className="flex flex-col gap-4">
            <SummaryCards summary={summary} />
            <Filters
              level={level}
              setLevel={setLevel}
              service={service}
              setService={setService}
              eventType={eventType}
              setEventType={setEventType}
              q={q}
              setQ={setQ}
              sinceHours={sinceHours}
              setSinceHours={setSinceHours}
              limit={limit}
              setLimit={setLimit}
              serviceOptions={serviceOptions}
              eventTypeOptions={eventTypeOptions}
              onRefresh={loadLogs}
            />

            {status === "loading" && !data && <LoadingState>Loading logs…</LoadingState>}

            {status === "error" && (
              <ErrorState>
                {error || "Failed to load logs from the API. Is the backend running?"}
              </ErrorState>
            )}

            {data && (
              <>
                <LogsTable data={data} onSelect={setSelectedLog} />
                <PaginationControls
                  offset={offset}
                  limit={limit}
                  total={data.summary.total_logs}
                  onOffsetChange={setOffset}
                />
              </>
            )}

            <PruneSection onPruned={() => { loadLogs(); loadSummary(); }} />
          </div>
        )}
      </main>

      {selectedLog && (
        <LogDetailModal log={selectedLog} onClose={() => setSelectedLog(null)} />
      )}
    </div>
  );
}

function SummaryCard({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="mb-1 text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      {children}
    </div>
  );
}

function SummaryCards({ summary }: { summary: ObservabilitySummary | null }) {
  if (!summary) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <SummaryCard key={i} label="…">
            <span className="text-sm text-neutral-500">{NA}</span>
          </SummaryCard>
        ))}
      </div>
    );
  }

  const workflow = summary.latest_market_workflow_run as
    | { status?: string; id?: number }
    | null;
  const refresh = summary.latest_price_refresh_run as { status?: string; id?: number } | null;
  const backup = summary.latest_backup as { filename?: string; created_at?: string } | null;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <SummaryCard label="Critical (24h)">
        <span
          className={`text-lg font-semibold ${summary.last_24h.critical > 0 ? "text-rose-300" : "text-neutral-100"}`}
        >
          {summary.last_24h.critical}
        </span>
      </SummaryCard>
      <SummaryCard label="Errors (24h)">
        <span
          className={`text-lg font-semibold ${summary.last_24h.error > 0 ? "text-rose-300" : "text-neutral-100"}`}
        >
          {summary.last_24h.error}
        </span>
      </SummaryCard>
      <SummaryCard label="Warnings (24h)">
        <span
          className={`text-lg font-semibold ${summary.last_24h.warning > 0 ? "text-amber-300" : "text-neutral-100"}`}
        >
          {summary.last_24h.warning}
        </span>
      </SummaryCard>
      <SummaryCard label="Latest workflow">
        <span className="text-sm font-medium text-neutral-100">
          {workflow ? naText(workflow.status) : NA}
        </span>
      </SummaryCard>
      <SummaryCard label="Latest price refresh">
        <span className="text-sm font-medium text-neutral-100">
          {refresh ? naText(refresh.status) : NA}
        </span>
      </SummaryCard>
      <SummaryCard label="Latest backup">
        <span className="text-sm font-medium text-neutral-100">
          {backup ? formatDateTime(backup.created_at ?? null) : NA}
        </span>
      </SummaryCard>
    </div>
  );
}

function Filters(props: {
  level: string;
  setLevel: (v: string) => void;
  service: string;
  setService: (v: string) => void;
  eventType: string;
  setEventType: (v: string) => void;
  q: string;
  setQ: (v: string) => void;
  sinceHours: string;
  setSinceHours: (v: string) => void;
  limit: number;
  setLimit: (v: number) => void;
  serviceOptions: string[];
  eventTypeOptions: string[];
  onRefresh: () => void;
}) {
  const selectClass =
    "rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-200";

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-neutral-800 bg-neutral-900 p-3">
      <select
        value={props.level}
        onChange={(e) => props.setLevel(e.target.value)}
        className={selectClass}
      >
        <option value="">All levels</option>
        {APP_LOG_LEVELS.map((l) => (
          <option key={l} value={l}>
            {l}
          </option>
        ))}
      </select>

      <select
        value={props.service}
        onChange={(e) => props.setService(e.target.value)}
        className={selectClass}
      >
        <option value="">All services</option>
        {props.serviceOptions.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>

      <select
        value={props.eventType}
        onChange={(e) => props.setEventType(e.target.value)}
        className={selectClass}
      >
        <option value="">All event types</option>
        {props.eventTypeOptions.map((e) => (
          <option key={e} value={e}>
            {e}
          </option>
        ))}
      </select>

      <input
        type="text"
        placeholder="Search message…"
        value={props.q}
        onChange={(e) => props.setQ(e.target.value)}
        className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-200 placeholder:text-neutral-600"
      />

      <select
        value={props.sinceHours}
        onChange={(e) => props.setSinceHours(e.target.value)}
        className={selectClass}
      >
        <option value="">All time</option>
        <option value="1">Last 1h</option>
        <option value="24">Last 24h</option>
        <option value="168">Last 7d</option>
        <option value="720">Last 30d</option>
      </select>

      <select
        value={String(props.limit)}
        onChange={(e) => props.setLimit(Number(e.target.value))}
        className={selectClass}
      >
        <option value="50">50 rows</option>
        <option value="100">100 rows</option>
        <option value="250">250 rows</option>
        <option value="500">500 rows</option>
      </select>

      <button
        type="button"
        onClick={props.onRefresh}
        className="rounded bg-neutral-100 px-2.5 py-1 text-xs font-medium text-neutral-900 hover:bg-white"
      >
        Refresh
      </button>
    </div>
  );
}

function LogsTable({
  data,
  onSelect,
}: {
  data: AppLogListResponse;
  onSelect: (log: AppLogEvent) => void;
}) {
  if (data.logs.length === 0) {
    return <EmptyState>No log events match these filters.</EmptyState>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-800">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
            <th className="px-2 py-1.5 font-medium">Time</th>
            <th className="px-2 py-1.5 font-medium">Level</th>
            <th className="px-2 py-1.5 font-medium">Service</th>
            <th className="px-2 py-1.5 font-medium">Event type</th>
            <th className="px-2 py-1.5 font-medium">Message</th>
            <th className="px-2 py-1.5 font-medium">Related</th>
            <th className="px-2 py-1.5 font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {data.logs.map((log) => {
            const isNoteworthy = log.level === "error" || log.level === "critical";
            const relatedHref = log.related_entity_type
              ? RELATED_ENTITY_LINKS[log.related_entity_type]
              : undefined;
            return (
              <tr
                key={log.id}
                className={`border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60 ${
                  isNoteworthy ? "bg-rose-950/10" : ""
                }`}
              >
                <td className="whitespace-nowrap px-2 py-1.5 text-neutral-400">
                  {formatDateTime(log.created_at)}
                </td>
                <td className="px-2 py-1.5">
                  <LogLevelBadge level={log.level} />
                </td>
                <td className="px-2 py-1.5 text-neutral-300">{log.service}</td>
                <td className="px-2 py-1.5 text-neutral-300">{log.event_type}</td>
                <td className="max-w-[24rem] px-2 py-1.5">
                  <span className="block truncate text-neutral-200" title={log.message}>
                    {log.message}
                  </span>
                </td>
                <td className="px-2 py-1.5 text-neutral-400">
                  {log.related_entity_type ? (
                    relatedHref ? (
                      <Link href={relatedHref} className="text-sky-400 hover:text-sky-300">
                        {log.related_entity_type}#{naText(log.related_entity_id)}
                      </Link>
                    ) : (
                      `${log.related_entity_type}#${naText(log.related_entity_id)}`
                    )
                  ) : (
                    <span className="text-neutral-600">{NA}</span>
                  )}
                </td>
                <td className="px-2 py-1.5">
                  <button
                    onClick={() => onSelect(log)}
                    className="text-xs font-medium text-neutral-400 hover:text-neutral-200"
                  >
                    View
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CollapsibleJson({ value }: { value: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-xs font-medium text-sky-400 hover:text-sky-300"
      >
        {open ? "Hide context JSON" : "Show context JSON"}
      </button>
      {open && (
        <pre className="mt-2 max-h-64 overflow-auto rounded border border-neutral-800 bg-neutral-950 p-2 text-[11px] text-neutral-300">
          {JSON.stringify(value, null, 2)}
        </pre>
      )}
    </div>
  );
}

function LogDetailModal({ log, onClose }: { log: AppLogEvent; onClose: () => void }) {
  const relatedHref = log.related_entity_type
    ? RELATED_ENTITY_LINKS[log.related_entity_type]
    : undefined;

  return (
    <div
      className="fixed inset-0 z-30 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-16"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-lg border border-neutral-800 bg-neutral-900 p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-4">
          <div className="flex items-center gap-2">
            <LogLevelBadge level={log.level} />
            <span className="text-sm font-semibold text-neutral-100">
              {log.service} / {log.event_type}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-xs font-medium text-neutral-500 hover:text-neutral-200"
          >
            Close
          </button>
        </div>

        <div className="mb-3 text-xs text-neutral-500">{formatDateTime(log.created_at)}</div>

        <p className="mb-4 whitespace-pre-wrap text-sm text-neutral-200">{log.message}</p>

        <div className="mb-3 grid grid-cols-2 gap-3 text-xs">
          <div>
            <div className="text-[11px] uppercase tracking-wide text-neutral-500">Related run</div>
            <div className="text-neutral-300">{naText(log.related_run_id)}</div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wide text-neutral-500">Related entity</div>
            <div className="text-neutral-300">
              {log.related_entity_type ? (
                relatedHref ? (
                  <Link href={relatedHref} className="text-sky-400 hover:text-sky-300">
                    {log.related_entity_type}#{naText(log.related_entity_id)}
                  </Link>
                ) : (
                  `${log.related_entity_type}#${naText(log.related_entity_id)}`
                )
              ) : (
                NA
              )}
            </div>
          </div>
        </div>

        {log.context && Object.keys(log.context).length > 0 && (
          <div className="mb-3">
            <CollapsibleJson value={log.context} />
          </div>
        )}

        {log.traceback && (
          <div>
            <div className="mb-1 text-[11px] uppercase tracking-wide text-neutral-500">
              Traceback
            </div>
            <pre className="max-h-64 overflow-auto rounded border border-neutral-800 bg-neutral-950 p-2 text-[11px] text-rose-200">
              {log.traceback}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

function PruneSection({ onPruned }: { onPruned: () => void }) {
  const [olderThanDays, setOlderThanDays] = useState(30);
  const [dryRun, setDryRun] = useState(true);
  const [confirm, setConfirm] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    dry_run: boolean;
    would_delete: number;
    deleted: number;
  } | null>(null);

  const needsConfirm = olderThanDays < 7;

  async function handlePrune() {
    setError(null);
    setPending(true);
    setResult(null);
    try {
      const response = await pruneAppLogs({
        older_than_days: olderThanDays,
        dry_run: dryRun,
        confirm: needsConfirm ? confirm : undefined,
      });
      setResult(response);
      if (!response.dry_run) onPruned();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to prune logs.");
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <h2 className="mb-3 text-sm font-semibold text-neutral-200">Prune logs</h2>
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-1.5 text-xs text-neutral-400">
          Older than (days)
          <input
            type="number"
            min={1}
            value={olderThanDays}
            onChange={(e) => setOlderThanDays(Number(e.target.value))}
            className="w-20 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-200"
          />
        </label>
        <label className="flex items-center gap-1.5 text-xs text-neutral-400">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => setDryRun(e.target.checked)}
            className="rounded border-neutral-700 bg-neutral-950"
          />
          Dry run
        </label>
        {needsConfirm && (
          <label className="flex items-center gap-1.5 text-xs text-neutral-400">
            Type PRUNE to confirm
            <input
              type="text"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className="w-24 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-200"
            />
          </label>
        )}
        <button
          type="button"
          onClick={handlePrune}
          disabled={pending || (needsConfirm && confirm !== "PRUNE")}
          className="rounded bg-neutral-100 px-3 py-1.5 text-xs font-medium text-neutral-900 hover:bg-white disabled:opacity-50"
        >
          {pending ? "Working…" : dryRun ? "Preview prune" : "Prune logs"}
        </button>
      </div>

      {error && <p className="mt-3 text-xs text-rose-300">{error}</p>}

      {result && (
        <p className="mt-3 text-xs text-neutral-400">
          {result.dry_run
            ? `Would delete ${result.would_delete} log(s).`
            : `Deleted ${result.deleted} log(s).`}
        </p>
      )}
    </section>
  );
}
