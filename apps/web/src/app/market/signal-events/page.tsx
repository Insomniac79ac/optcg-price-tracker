"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { MarketSignalEventStatusBadge } from "@/components/MarketSignalEventStatusBadge";
import { RarityBadge } from "@/components/RarityBadge";
import { SeverityBadge } from "@/components/SeverityBadge";
import {
  MARKET_SIGNAL_EVENT_STATUSES,
  MARKET_SIGNAL_TYPES,
  MARKET_SUGGESTED_ACTIONS,
  type MarketSignalEvent,
  type MarketSignalEventsSummary,
  dismissMarketSignalEvent,
  fetchMarketSignalEvents,
  patchMarketSignalEvent,
  resolveMarketSignalEvent,
  watchMarketSignalEvent,
} from "@/lib/api";
import { cardDisplayName, formatDateTime } from "@/lib/format";

const SIGNAL_TYPE_LABELS: Record<string, string> = {
  price_up_7d: "Price up (7d)",
  price_down_7d: "Price down (7d)",
  price_up_30d: "Price up (30d)",
  price_down_30d: "Price down (30d)",
  yuyutei_buy_sell_spread_compressed: "Yuyu-Tei spread compressed",
  yuyutei_buy_sell_spread_wide: "Yuyu-Tei spread wide",
  snkrdunk_floor_below_yuyutei_sell: "SNKRDUNK below Yuyu-Tei",
  snkrdunk_floor_above_yuyutei_sell: "SNKRDUNK above Yuyu-Tei",
  owned_above_target_sell: "Owned: above target",
  owned_below_cost_basis: "Owned: below cost basis",
  missing_recent_price: "Missing recent price",
  stale_mapping_price: "Stale mapping price",
};

const SUGGESTED_ACTION_LABELS: Record<string, string> = {
  review_buy_opportunity: "Review buy opportunity",
  review_sell_opportunity: "Review sell opportunity",
  monitor_momentum: "Monitor momentum",
  monitor_drop: "Monitor drop",
  review_mapping: "Review mapping",
  update_prices: "Update prices",
  add_collection_target: "Add collection target",
  none: "—",
};

const ALL_OPTION = { value: "", label: "All" };
const STATUS_OPTIONS = [
  ALL_OPTION,
  ...MARKET_SIGNAL_EVENT_STATUSES.map((s) => ({ value: s, label: s })),
];
const SIGNAL_TYPE_OPTIONS = [
  ALL_OPTION,
  ...MARKET_SIGNAL_TYPES.map((t) => ({ value: t, label: SIGNAL_TYPE_LABELS[t] ?? t })),
];
const SUGGESTED_ACTION_OPTIONS = [
  ALL_OPTION,
  ...MARKET_SUGGESTED_ACTIONS.map((a) => ({ value: a, label: SUGGESTED_ACTION_LABELS[a] ?? a })),
];
const OWNED_OPTIONS = [
  { value: "", label: "All" },
  { value: "true", label: "Owned only" },
  { value: "false", label: "Unowned only" },
];
const LIMIT_OPTIONS = [25, 50, 100] as const;

function topEntry(counts: Record<string, number>, labels: Record<string, string>): string {
  let best: string | null = null;
  let bestCount = 0;
  for (const [key, count] of Object.entries(counts)) {
    if (count > bestCount) {
      best = key;
      bestCount = count;
    }
  }
  if (best === null) return "—";
  return `${labels[best] ?? best} (${bestCount})`;
}

export default function MarketSignalEventsPage() {
  const [events, setEvents] = useState<MarketSignalEvent[]>([]);
  const [summary, setSummary] = useState<MarketSignalEventsSummary | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");

  const [statusFilter, setStatusFilter] = useState("");
  const [signalTypeFilter, setSignalTypeFilter] = useState("");
  const [suggestedActionFilter, setSuggestedActionFilter] = useState("");
  const [cardCodeInput, setCardCodeInput] = useState("");
  const [cardCodeFilter, setCardCodeFilter] = useState("");
  const [ownedFilter, setOwnedFilter] = useState("");
  const [limit, setLimit] = useState<number>(100);

  const [actionMessage, setActionMessage] = useState<
    { type: "success" | "error"; text: string } | null
  >(null);
  const [pendingActionId, setPendingActionId] = useState<number | null>(null);
  const [editingNotesId, setEditingNotesId] = useState<number | null>(null);
  const [notesDraft, setNotesDraft] = useState("");

  useEffect(() => {
    const handle = setTimeout(() => setCardCodeFilter(cardCodeInput.trim()), 300);
    return () => clearTimeout(handle);
  }, [cardCodeInput]);

  function refresh() {
    setStatus("loading");
    fetchMarketSignalEvents({
      status: statusFilter || undefined,
      signal_type: signalTypeFilter || undefined,
      suggested_action: suggestedActionFilter || undefined,
      card_code: cardCodeFilter || undefined,
      owned: ownedFilter === "" ? undefined : ownedFilter === "true",
      limit,
    })
      .then((data) => {
        setEvents(data.events);
        setSummary(data.summary);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, signalTypeFilter, suggestedActionFilter, cardCodeFilter, ownedFilter, limit]);

  async function handleWatch(event: MarketSignalEvent) {
    setActionMessage(null);
    setPendingActionId(event.id);
    try {
      await watchMarketSignalEvent(event.id);
      setActionMessage({ type: "success", text: `Event #${event.id} marked as watching.` });
      refresh();
    } catch {
      setActionMessage({ type: "error", text: `Failed to update event #${event.id}.` });
    } finally {
      setPendingActionId(null);
    }
  }

  async function handleDismiss(event: MarketSignalEvent) {
    setActionMessage(null);
    setPendingActionId(event.id);
    try {
      await dismissMarketSignalEvent(event.id);
      setActionMessage({ type: "success", text: `Event #${event.id} dismissed.` });
      refresh();
    } catch {
      setActionMessage({ type: "error", text: `Failed to update event #${event.id}.` });
    } finally {
      setPendingActionId(null);
    }
  }

  async function handleResolve(event: MarketSignalEvent) {
    setActionMessage(null);
    setPendingActionId(event.id);
    try {
      await resolveMarketSignalEvent(event.id);
      setActionMessage({ type: "success", text: `Event #${event.id} resolved.` });
      refresh();
    } catch {
      setActionMessage({ type: "error", text: `Failed to update event #${event.id}.` });
    } finally {
      setPendingActionId(null);
    }
  }

  function startEditNotes(event: MarketSignalEvent) {
    setEditingNotesId(event.id);
    setNotesDraft(event.notes ?? "");
  }

  function cancelEditNotes() {
    setEditingNotesId(null);
    setNotesDraft("");
  }

  async function saveNotes(event: MarketSignalEvent) {
    setActionMessage(null);
    setPendingActionId(event.id);
    try {
      await patchMarketSignalEvent(event.id, { notes: notesDraft });
      setActionMessage({ type: "success", text: `Notes updated for event #${event.id}.` });
      setEditingNotesId(null);
      refresh();
    } catch {
      setActionMessage({ type: "error", text: `Failed to update notes for event #${event.id}.` });
    } finally {
      setPendingActionId(null);
    }
  }

  const topSignalType = useMemo(
    () => (summary ? topEntry(summary.by_signal_type, SIGNAL_TYPE_LABELS) : "—"),
    [summary],
  );
  const topSuggestedAction = useMemo(
    () => (summary ? topEntry(summary.by_suggested_action, SUGGESTED_ACTION_LABELS) : "—"),
    [summary],
  );

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-4 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">
            Signal events
          </h1>
          {status === "ready" && (
            <span className="text-sm text-neutral-500">
              {events.length} event{events.length === 1 ? "" : "s"}
            </span>
          )}
        </div>

        {summary && (
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
            <StatCard label="Total events" value={summary.total_events} />
            <StatCard label="Open" value={summary.open_events} />
            <StatCard label="Watching" value={summary.watching_events} />
            <StatCard label="Dismissed" value={summary.dismissed_events} />
            <StatCard label="Resolved" value={summary.resolved_events} />
            <StatCard label="Top signal type" value={topSignalType} />
            <StatCard label="Top suggested action" value={topSuggestedAction} />
          </div>
        )}

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <FilterSelect
            label="Status"
            value={statusFilter}
            onChange={setStatusFilter}
            options={STATUS_OPTIONS}
          />
          <FilterSelect
            label="Signal type"
            value={signalTypeFilter}
            onChange={setSignalTypeFilter}
            options={SIGNAL_TYPE_OPTIONS}
          />
          <FilterSelect
            label="Suggested action"
            value={suggestedActionFilter}
            onChange={setSuggestedActionFilter}
            options={SUGGESTED_ACTION_OPTIONS}
          />
          <label className="flex items-center gap-1.5 text-xs text-neutral-500">
            Card code
            <input
              type="text"
              value={cardCodeInput}
              onChange={(e) => setCardCodeInput(e.target.value)}
              placeholder="OP01-001"
              className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200 placeholder:text-neutral-600"
            />
          </label>
          <FilterSelect
            label="Owned"
            value={ownedFilter}
            onChange={setOwnedFilter}
            options={OWNED_OPTIONS}
          />
          <FilterSelect
            label="Limit"
            value={String(limit)}
            onChange={(v) => setLimit(Number(v))}
            options={LIMIT_OPTIONS.map((n) => ({ value: String(n), label: String(n) }))}
          />
        </div>

        {actionMessage && (
          <div
            className={`mb-4 rounded border px-3 py-2 text-xs ${
              actionMessage.type === "success"
                ? "border-emerald-900/50 bg-emerald-950/30 text-emerald-300"
                : "border-rose-900/50 bg-rose-950/30 text-rose-300"
            }`}
          >
            {actionMessage.text}
          </div>
        )}

        {status === "loading" && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            Loading signal events…
          </div>
        )}

        {status === "error" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Failed to load signal events from the API.
          </div>
        )}

        {status === "ready" && events.length === 0 && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            No signal events found
          </div>
        )}

        {status === "ready" && events.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-neutral-800">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                  <th className="px-2 py-1.5 font-medium">Status</th>
                  <th className="px-2 py-1.5 font-medium">Severity</th>
                  <th className="px-2 py-1.5 font-medium">Signal type</th>
                  <th className="px-2 py-1.5 font-medium">Code</th>
                  <th className="px-2 py-1.5 font-medium">Name</th>
                  <th className="px-2 py-1.5 font-medium">Set</th>
                  <th className="px-2 py-1.5 font-medium">Rarity</th>
                  <th className="px-2 py-1.5 font-medium">Owned</th>
                  <th className="px-2 py-1.5 font-medium">Suggested action</th>
                  <th className="px-2 py-1.5 font-medium">Message</th>
                  <th className="px-2 py-1.5 font-medium">First seen</th>
                  <th className="px-2 py-1.5 font-medium">Last seen</th>
                  <th className="px-2 py-1.5 font-medium">Seen</th>
                  <th className="px-2 py-1.5 font-medium">Notes</th>
                  <th className="px-2 py-1.5 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => {
                  const isPending = pendingActionId === event.id;
                  const isEditingNotes = editingNotesId === event.id;
                  return (
                    <tr
                      key={event.id}
                      className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                    >
                      <td className="px-2 py-1.5">
                        <MarketSignalEventStatusBadge status={event.status} />
                      </td>
                      <td className="px-2 py-1.5">
                        <SeverityBadge severity={event.severity} />
                      </td>
                      <td className="px-2 py-1.5 text-neutral-300">
                        {SIGNAL_TYPE_LABELS[event.signal_type] ?? event.signal_type}
                      </td>
                      <td className="px-2 py-1.5 font-mono text-neutral-400">
                        {event.card_id !== null ? (
                          <Link href={`/cards/${event.card_id}`} className="hover:text-sky-400">
                            {event.card_code ?? "—"}
                          </Link>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-2 py-1.5 font-medium text-neutral-100">
                        {event.card_id !== null ? cardDisplayName(event) : "—"}
                      </td>
                      <td className="px-2 py-1.5 text-neutral-400">
                        {event.set_code ?? "—"}
                      </td>
                      <td className="px-2 py-1.5">
                        {event.rarity ? <RarityBadge rarity={event.rarity} /> : "—"}
                      </td>
                      <td className="px-2 py-1.5 text-neutral-200">
                        {event.owned_quantity > 0 ? (
                          <Link href="/collection" className="hover:text-sky-400">
                            {event.owned_quantity}
                          </Link>
                        ) : (
                          0
                        )}
                      </td>
                      <td className="px-2 py-1.5 text-neutral-300">
                        {event.suggested_action
                          ? SUGGESTED_ACTION_LABELS[event.suggested_action] ?? event.suggested_action
                          : "—"}
                      </td>
                      <td className="max-w-[16rem] px-2 py-1.5 text-neutral-400">
                        {event.message ?? "—"}
                      </td>
                      <td className="whitespace-nowrap px-2 py-1.5 text-neutral-400">
                        {formatDateTime(event.first_seen_at)}
                      </td>
                      <td className="whitespace-nowrap px-2 py-1.5 text-neutral-400">
                        {formatDateTime(event.last_seen_at)}
                      </td>
                      <td className="px-2 py-1.5">
                        <span
                          className={`font-semibold ${
                            event.seen_count > 1 ? "text-amber-300" : "text-neutral-300"
                          }`}
                        >
                          {event.seen_count}
                        </span>
                      </td>
                      <td className="min-w-[10rem] px-2 py-1.5 text-neutral-400">
                        {isEditingNotes ? (
                          <div className="flex items-center gap-1">
                            <input
                              type="text"
                              value={notesDraft}
                              onChange={(e) => setNotesDraft(e.target.value)}
                              className="w-32 rounded border border-neutral-700 bg-neutral-950 px-1.5 py-0.5 text-xs text-neutral-100"
                              autoFocus
                            />
                            <button
                              onClick={() => saveNotes(event)}
                              disabled={isPending}
                              className="text-emerald-400 hover:text-emerald-300 disabled:opacity-50"
                            >
                              Save
                            </button>
                            <button
                              onClick={cancelEditNotes}
                              disabled={isPending}
                              className="text-neutral-500 hover:text-neutral-300 disabled:opacity-50"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <span>{event.notes ?? "—"}</span>
                        )}
                      </td>
                      <td className="px-2 py-1.5">
                        <div className="flex flex-wrap gap-2">
                          {event.status !== "watching" && (
                            <button
                              onClick={() => handleWatch(event)}
                              disabled={isPending}
                              className="text-xs font-medium text-violet-400 hover:text-violet-300 disabled:opacity-50"
                            >
                              Watch
                            </button>
                          )}
                          {event.status !== "dismissed" && (
                            <button
                              onClick={() => handleDismiss(event)}
                              disabled={isPending}
                              className="text-xs font-medium text-neutral-400 hover:text-neutral-200 disabled:opacity-50"
                            >
                              Dismiss
                            </button>
                          )}
                          {event.status !== "resolved" && (
                            <button
                              onClick={() => handleResolve(event)}
                              disabled={isPending}
                              className="text-xs font-medium text-emerald-400 hover:text-emerald-300 disabled:opacity-50"
                            >
                              Resolve
                            </button>
                          )}
                          {!isEditingNotes && (
                            <button
                              onClick={() => startEditNotes(event)}
                              disabled={isPending}
                              className="text-xs font-medium text-sky-400 hover:text-sky-300 disabled:opacity-50"
                            >
                              Edit notes
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">
        {label}
      </div>
      <div className="mt-1 truncate text-2xl font-semibold text-neutral-100">
        {value}
      </div>
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
