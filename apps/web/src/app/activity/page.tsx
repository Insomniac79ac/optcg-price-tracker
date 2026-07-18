"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { PaginationControls } from "@/components/PaginationControls";
import { SearchTypeBadge } from "@/components/SearchTypeBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import {
  ACTIVITY_EVENT_SOURCES,
  type CollectorActivityEvent,
  type CollectorActivityListSummary,
  fetchCollectorActivity,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";

const ALL_OPTION = { value: "", label: "All" };
const SOURCE_OPTIONS = [
  ALL_OPTION,
  ...ACTIVITY_EVENT_SOURCES.map((s) => ({ value: s, label: s.replace("_", " ") })),
];
const LIMIT_OPTIONS = [50, 100, 200] as const;

export default function ActivityPage() {
  const [events, setEvents] = useState<CollectorActivityEvent[]>([]);
  const [summary, setSummary] = useState<CollectorActivityListSummary | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [sourceFilter, setSourceFilter] = useState("");
  const [limit, setLimit] = useState<number>(100);
  const [offset, setOffset] = useState(0);

  // Any filter/page-size change re-pages to the start - an offset from the
  // old filter's result set is otherwise almost certainly out of range for
  // the new one.
  useEffect(() => {
    setOffset(0);
  }, [sourceFilter, limit]);

  useEffect(() => {
    setStatus("loading");
    fetchCollectorActivity({ event_source: sourceFilter || undefined, limit, offset })
      .then((data) => {
        setEvents(data.events);
        setSummary(data.summary);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, [sourceFilter, limit, offset]);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-6xl px-4 py-6">
        <div className="mb-4 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">Activity</h1>
          {status === "ready" && (
            <span className="text-sm text-neutral-500">
              {events.length} event{events.length === 1 ? "" : "s"}
            </span>
          )}
        </div>
        <p className="mb-4 text-sm text-neutral-500">
          A log of notable actions across your collection, wishlist, grading, market signals,
          reports, backups, and workflow runs.
        </p>

        {summary && (
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Total events" value={summary.total_events} />
            {Object.entries(summary.by_source)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 3)
              .map(([source, count]) => (
                <StatCard key={source} label={source.replace("_", " ")} value={count} />
              ))}
          </div>
        )}

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <FilterSelect
            label="Source"
            value={sourceFilter}
            onChange={setSourceFilter}
            options={SOURCE_OPTIONS}
          />
          <FilterSelect
            label="Limit"
            value={String(limit)}
            onChange={(v) => setLimit(Number(v))}
            options={LIMIT_OPTIONS.map((n) => ({ value: String(n), label: String(n) }))}
          />
        </div>

        {status === "loading" && <LoadingState>Loading activity…</LoadingState>}

        {status === "error" && <ErrorState>Failed to load activity from the API.</ErrorState>}

        {status === "ready" && events.length === 0 && (
          <EmptyState>
            No activity recorded yet. Actions across your collection, wishlist, grading, and
            market intelligence will show up here.
          </EmptyState>
        )}

        {status === "ready" && events.length > 0 && (
          <div className="mb-3 divide-y divide-neutral-900 rounded-lg border border-neutral-800">
            {events.map((event) => (
              <div key={event.id} className="flex items-start justify-between gap-3 px-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <SearchTypeBadge type={event.event_source} />
                    <span className="truncate text-sm font-medium text-neutral-100">
                      {event.title}
                    </span>
                  </div>
                  {event.message && (
                    <div className="mt-0.5 text-xs text-neutral-500">{event.message}</div>
                  )}
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-neutral-600">
                    <span>{event.event_type}</span>
                    {event.card_code && (
                      <Link
                        href={`/cards/${event.card_id}`}
                        className="font-mono text-neutral-500 hover:text-sky-400"
                      >
                        {event.card_code}
                      </Link>
                    )}
                  </div>
                </div>
                <span className="shrink-0 whitespace-nowrap text-xs text-neutral-500">
                  {formatDateTime(event.created_at)}
                </span>
              </div>
            ))}
          </div>
        )}

        {status === "ready" && summary && (
          <PaginationControls
            offset={offset}
            limit={limit}
            total={summary.total_events}
            onOffsetChange={setOffset}
          />
        )}
      </main>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="truncate text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className="mt-1 truncate text-2xl font-semibold text-neutral-100">{value}</div>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-neutral-500">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}
