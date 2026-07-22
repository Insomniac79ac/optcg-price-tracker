"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { AdminAuthGate } from "@/components/AdminAuthGate";
import { AdminLogoutButton } from "@/components/AdminLogoutButton";
import { AppHeader } from "@/components/AppHeader";
import { LogLevelBadge } from "@/components/LogLevelBadge";
import { PaginationControls } from "@/components/PaginationControls";
import { ErrorState, LoadingState } from "@/components/StateBlocks";
import { ActionButton } from "@/components/ui/ActionButton";
import { DataTableShell, TABLE_ROW_WARNING_CLASS } from "@/components/ui/DataTableShell";
import { FILTER_INPUT_CLASS } from "@/components/ui/FilterBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatCard, StatGrid } from "@/components/ui/StatCard";
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
  return (
    <Suspense fallback={null}>
      <AdminLogsPageInner />
    </Suspense>
  );
}

function AdminLogsPageInner() {
  // Lets other pages (e.g. /admin/performance's "largest recent responses"
  // section) deep-link here pre-filtered, e.g. ?event_type=response_size_warning.
  const searchParams = useSearchParams();
  const initialEventType = searchParams.get("event_type") ?? ALL_OPTION;

  const [unauthorized, setUnauthorized] = useState(false);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [error, setError] = useState<string | null>(null);

  const [summary, setSummary] = useState<ObservabilitySummary | null>(null);
  const [data, setData] = useState<AppLogListResponse | null>(null);
  const [selectedLog, setSelectedLog] = useState<AppLogEvent | null>(null);

  const [level, setLevel] = useState(ALL_OPTION);
  const [service, setService] = useState(ALL_OPTION);
  const [eventType, setEventType] = useState(initialEventType);
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
        <PageHeader
          title="App logs"
          description="Recent app, worker, backup, import, and workflow events."
          actions={<AdminLogoutButton />}
        />
        <div className="mb-4 flex flex-wrap gap-3 text-xs text-text-muted">
          <Link href="/admin/actions" className="text-sky-400 hover:underline">
            Admin actions
          </Link>
          <Link href="/admin/data-retention" className="text-sky-400 hover:underline">
            Data retention
          </Link>
        </div>

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

function SummaryCards({ summary }: { summary: ObservabilitySummary | null }) {
  if (!summary) {
    return (
      <StatGrid>
        {Array.from({ length: 6 }).map((_, i) => (
          <StatCard key={i} label="…" value={NA} />
        ))}
      </StatGrid>
    );
  }

  const workflow = summary.latest_market_workflow_run as
    | { status?: string; id?: number }
    | null;
  const refresh = summary.latest_price_refresh_run as { status?: string; id?: number } | null;
  const backup = summary.latest_backup as { filename?: string; created_at?: string } | null;

  return (
    <StatGrid>
      <StatCard
        label="Critical (24h)"
        value={summary.last_24h.critical}
        tone={summary.last_24h.critical > 0 ? "bad" : "neutral"}
      />
      <StatCard
        label="Errors (24h)"
        value={summary.last_24h.error}
        tone={summary.last_24h.error > 0 ? "bad" : "neutral"}
      />
      <StatCard
        label="Warnings (24h)"
        value={summary.last_24h.warning}
        tone={summary.last_24h.warning > 0 ? "bad" : "neutral"}
      />
      <StatCard label="Latest workflow" value={workflow ? naText(workflow.status) : NA} />
      <StatCard label="Latest price refresh" value={refresh ? naText(refresh.status) : NA} />
      <StatCard
        label="Latest backup"
        value={backup ? formatDateTime(backup.created_at ?? null) : NA}
      />
    </StatGrid>
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
  return (
    <div className="panel flex flex-wrap items-center gap-2 p-3">
      <select
        value={props.level}
        onChange={(e) => props.setLevel(e.target.value)}
        className={FILTER_INPUT_CLASS}
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
        className={FILTER_INPUT_CLASS}
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
        className={FILTER_INPUT_CLASS}
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
        className={FILTER_INPUT_CLASS}
      />

      <select
        value={props.sinceHours}
        onChange={(e) => props.setSinceHours(e.target.value)}
        className={FILTER_INPUT_CLASS}
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
        className={FILTER_INPUT_CLASS}
      >
        <option value="50">50 rows</option>
        <option value="100">100 rows</option>
        <option value="250">250 rows</option>
        <option value="500">500 rows</option>
      </select>

      <ActionButton onClick={props.onRefresh}>Refresh</ActionButton>
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
  return (
    <DataTableShell isEmpty={data.logs.length === 0} emptyLabel="No log events match these filters.">
      <table className="data-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Level</th>
            <th>Service</th>
            <th>Event type</th>
            <th>Message</th>
            <th>Related</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {data.logs.map((log) => {
            const isNoteworthy = log.level === "error" || log.level === "critical";
            const relatedHref = log.related_entity_type
              ? RELATED_ENTITY_LINKS[log.related_entity_type]
              : undefined;
            return (
              <tr key={log.id} className={isNoteworthy ? TABLE_ROW_WARNING_CLASS : undefined}>
                <td className="mono whitespace-nowrap text-text-secondary">
                  {formatDateTime(log.created_at)}
                </td>
                <td>
                  <LogLevelBadge level={log.level} />
                </td>
                <td className="text-text-secondary">{log.service}</td>
                <td className="text-text-secondary">{log.event_type}</td>
                <td className="max-w-[24rem]">
                  <span className="block truncate text-text-primary" title={log.message}>
                    {log.message}
                  </span>
                </td>
                <td className="text-text-secondary">
                  {log.related_entity_type ? (
                    relatedHref ? (
                      <Link href={relatedHref} className="text-sky-400 hover:underline">
                        {log.related_entity_type}#{naText(log.related_entity_id)}
                      </Link>
                    ) : (
                      `${log.related_entity_type}#${naText(log.related_entity_id)}`
                    )
                  ) : (
                    <span className="text-text-faint">{NA}</span>
                  )}
                </td>
                <td>
                  <ActionButton onClick={() => onSelect(log)}>View</ActionButton>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </DataTableShell>
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
        <pre className="mt-2 max-h-64 overflow-auto rounded-control border border-border-default bg-bg-page p-2 text-[11px] text-text-secondary">
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
        className="w-full max-w-2xl rounded-modal border border-border-default bg-bg-elevated p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-4">
          <div className="flex items-center gap-2">
            <LogLevelBadge level={log.level} />
            <span className="text-sm font-semibold text-text-primary">
              {log.service} / {log.event_type}
            </span>
          </div>
          <ActionButton onClick={onClose}>Close</ActionButton>
        </div>

        <div className="mb-3 text-xs text-text-muted">{formatDateTime(log.created_at)}</div>

        <p className="mb-4 whitespace-pre-wrap text-sm text-text-primary">{log.message}</p>

        <div className="mb-3 grid grid-cols-2 gap-3 text-xs">
          <div>
            <div className="text-[11px] uppercase tracking-wide text-text-muted">Related run</div>
            <div className="text-text-secondary">{naText(log.related_run_id)}</div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wide text-text-muted">Related entity</div>
            <div className="text-text-secondary">
              {log.related_entity_type ? (
                relatedHref ? (
                  <Link href={relatedHref} className="text-sky-400 hover:underline">
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
            <div className="mb-1 text-[11px] uppercase tracking-wide text-text-muted">
              Traceback
            </div>
            <pre className="max-h-64 overflow-auto rounded-control border border-signal-red/40 bg-signal-red/10 p-2 text-[11px] text-signal-red">
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
    <section className="panel p-4">
      <h2 className="mb-3 text-sm font-semibold text-text-primary">Prune logs</h2>
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          Older than (days)
          <input
            type="number"
            min={1}
            value={olderThanDays}
            onChange={(e) => setOlderThanDays(Number(e.target.value))}
            className={`w-20 ${FILTER_INPUT_CLASS}`}
          />
        </label>
        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
          Dry run
        </label>
        {needsConfirm && (
          <label className="flex items-center gap-1.5 text-xs text-text-secondary">
            Type PRUNE to confirm
            <input
              type="text"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className={`w-24 ${FILTER_INPUT_CLASS}`}
            />
          </label>
        )}
        <ActionButton
          variant={dryRun ? "dry-run" : "danger"}
          onClick={handlePrune}
          disabled={pending || (needsConfirm && confirm !== "PRUNE")}
        >
          {pending ? "Working…" : dryRun ? "Preview prune" : "Prune logs"}
        </ActionButton>
      </div>

      {error && <p className="mt-3 text-xs text-signal-red">{error}</p>}

      {result && (
        <p className="mt-3 text-xs text-text-secondary">
          {result.dry_run
            ? `Would delete ${result.would_delete} log(s).`
            : `Deleted ${result.deleted} log(s).`}
        </p>
      )}
    </section>
  );
}
