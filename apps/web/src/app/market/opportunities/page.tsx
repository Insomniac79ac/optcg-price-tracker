"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { CollectorGroupLabel } from "@/components/CollectorGroupLabel";
import { CollectorTagBadge } from "@/components/CollectorTagBadge";
import { GradingStatusBadge } from "@/components/GradingStatusBadge";
import { MarketSignalEventStatusBadge } from "@/components/MarketSignalEventStatusBadge";
import { OpportunityCategoryBadge } from "@/components/OpportunityCategoryBadge";
import { PaginationControls } from "@/components/PaginationControls";
import { RarityBadge } from "@/components/RarityBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateBlocks";
import { WishlistPriorityBadge } from "@/components/WishlistPriorityBadge";
import {
  OPPORTUNITY_CATEGORIES,
  type MarketOpportunitiesSummary,
  type MarketOpportunity,
  dismissMarketSignalEvent,
  fetchMarketOpportunities,
  resolveMarketSignalEvent,
  watchMarketSignalEvent,
} from "@/lib/api";
import { cardDisplayName, formatDateTime, formatJpy } from "@/lib/format";

const ALL_OPTION = { value: "", label: "All" };
const CATEGORY_OPTIONS = [
  ALL_OPTION,
  ...OPPORTUNITY_CATEGORIES.map((c) => ({ value: c, label: c.replace("_", " ") })),
];
const OWNED_OPTIONS = [
  { value: "", label: "All" },
  { value: "true", label: "Owned only" },
  { value: "false", label: "Unowned only" },
];
const LIMIT_OPTIONS = [25, 50, 100] as const;

function scoreColor(score: number): string {
  if (score >= 70) return "text-emerald-300";
  if (score >= 40) return "text-amber-300";
  return "text-neutral-400";
}

export default function MarketOpportunitiesPage() {
  const [opportunities, setOpportunities] = useState<MarketOpportunity[]>([]);
  const [summary, setSummary] = useState<MarketOpportunitiesSummary | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");

  const [categoryFilter, setCategoryFilter] = useState("");
  const [ownedFilter, setOwnedFilter] = useState("");
  const [setCodeInput, setSetCodeInput] = useState("");
  const [setCodeFilter, setSetCodeFilter] = useState("");
  const [rarityInput, setRarityInput] = useState("");
  const [rarityFilter, setRarityFilter] = useState("");
  const [minScoreInput, setMinScoreInput] = useState("");
  const [minScoreFilter, setMinScoreFilter] = useState<number | undefined>(undefined);
  const [limit, setLimit] = useState<number>(100);
  const [offset, setOffset] = useState(0);
  const [tagFilter, setTagFilter] = useState("");
  const [groupFilter, setGroupFilter] = useState("");

  const [actionMessage, setActionMessage] = useState<
    { type: "success" | "error"; text: string } | null
  >(null);
  const [pendingActionId, setPendingActionId] = useState<number | null>(null);

  useEffect(() => {
    const handle = setTimeout(() => setSetCodeFilter(setCodeInput.trim()), 300);
    return () => clearTimeout(handle);
  }, [setCodeInput]);

  useEffect(() => {
    const handle = setTimeout(() => setRarityFilter(rarityInput.trim()), 300);
    return () => clearTimeout(handle);
  }, [rarityInput]);

  useEffect(() => {
    const handle = setTimeout(() => {
      const trimmed = minScoreInput.trim();
      setMinScoreFilter(trimmed === "" ? undefined : Number(trimmed));
    }, 300);
    return () => clearTimeout(handle);
  }, [minScoreInput]);

  function refresh() {
    setStatus("loading");
    fetchMarketOpportunities({
      category: categoryFilter || undefined,
      owned: ownedFilter === "" ? undefined : ownedFilter === "true",
      set_code: setCodeFilter || undefined,
      rarity: rarityFilter || undefined,
      min_score: minScoreFilter,
      limit,
      offset,
    })
      .then((data) => {
        setOpportunities(data.opportunities);
        setSummary(data.summary);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }

  // Any filter/page-size change re-pages to the start - an offset from the
  // old filter's result set is otherwise almost certainly out of range for
  // the new one.
  useEffect(() => {
    setOffset(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categoryFilter, ownedFilter, setCodeFilter, rarityFilter, minScoreFilter, limit]);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categoryFilter, ownedFilter, setCodeFilter, rarityFilter, minScoreFilter, limit, offset]);

  // The backend doesn't support filtering opportunities by tag/group, so
  // these two filters apply client-side to whatever page of rows is already
  // loaded - the tag/group dropdown options are likewise derived only from
  // those loaded rows, not a separate full tag/group list.
  const tagOptions = useMemo(() => {
    const seen = new Map<number, string>();
    for (const opp of opportunities) {
      for (const tag of opp.tags) seen.set(tag.id, tag.name);
    }
    return [
      ALL_OPTION,
      ...Array.from(seen.entries())
        .sort((a, b) => a[1].localeCompare(b[1]))
        .map(([id, name]) => ({ value: String(id), label: name })),
    ];
  }, [opportunities]);

  const groupOptions = useMemo(() => {
    const seen = new Map<number, string>();
    for (const opp of opportunities) {
      for (const group of opp.groups) seen.set(group.id, group.name);
    }
    return [
      ALL_OPTION,
      ...Array.from(seen.entries())
        .sort((a, b) => a[1].localeCompare(b[1]))
        .map(([id, name]) => ({ value: String(id), label: name })),
    ];
  }, [opportunities]);

  const filteredOpportunities = useMemo(() => {
    return opportunities.filter((opp) => {
      if (tagFilter && !opp.tags.some((t) => String(t.id) === tagFilter)) return false;
      if (groupFilter && !opp.groups.some((g) => String(g.id) === groupFilter)) return false;
      return true;
    });
  }, [opportunities, tagFilter, groupFilter]);

  async function handleWatch(opp: MarketOpportunity) {
    setActionMessage(null);
    setPendingActionId(opp.event_id);
    try {
      await watchMarketSignalEvent(opp.event_id);
      setActionMessage({ type: "success", text: `Event #${opp.event_id} marked as watching.` });
      refresh();
    } catch {
      setActionMessage({ type: "error", text: `Failed to update event #${opp.event_id}.` });
    } finally {
      setPendingActionId(null);
    }
  }

  async function handleDismiss(opp: MarketOpportunity) {
    setActionMessage(null);
    setPendingActionId(opp.event_id);
    try {
      await dismissMarketSignalEvent(opp.event_id);
      setActionMessage({ type: "success", text: `Event #${opp.event_id} dismissed.` });
      refresh();
    } catch {
      setActionMessage({ type: "error", text: `Failed to update event #${opp.event_id}.` });
    } finally {
      setPendingActionId(null);
    }
  }

  async function handleResolve(opp: MarketOpportunity) {
    setActionMessage(null);
    setPendingActionId(opp.event_id);
    try {
      await resolveMarketSignalEvent(opp.event_id);
      setActionMessage({ type: "success", text: `Event #${opp.event_id} resolved.` });
      refresh();
    } catch {
      setActionMessage({ type: "error", text: `Failed to update event #${opp.event_id}.` });
    } finally {
      setPendingActionId(null);
    }
  }

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-4 flex items-baseline justify-between">
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-semibold text-neutral-100">
              Market opportunities
            </h1>
            <Link
              href="/market/signal-events"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Review signal events
            </Link>
            <Link
              href="/market/signals"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Market signals
            </Link>
            <Link
              href="/market/report"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Market report
            </Link>
            <Link
              href="/analytics/sell-decisions"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Sell decision support
            </Link>
          </div>
          {status === "ready" && (
            <span className="text-sm text-neutral-500">
              {filteredOpportunities.length} of {opportunities.length} opportunit
              {opportunities.length === 1 ? "y" : "ies"}
            </span>
          )}
        </div>

        {summary && (
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-9">
            <StatCard label="Total" value={summary.total_opportunities} />
            <StatCard label="Avg score" value={summary.average_score} />
            <StatCard label="Highest" value={summary.highest_score} />
            <StatCard label="Buy" value={summary.by_category.buy ?? 0} />
            <StatCard label="Sell" value={summary.by_category.sell ?? 0} />
            <StatCard label="Momentum" value={summary.by_category.momentum ?? 0} />
            <StatCard label="Drops" value={summary.by_category.drop ?? 0} />
            <StatCard label="Data quality" value={summary.by_category.data_quality ?? 0} />
            <StatCard label="Owned" value={summary.by_category.owned ?? 0} />
            <StatCard label="Wishlist target hit" value={summary.wishlist_target_hit_count} />
          </div>
        )}

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <FilterSelect
            label="Category"
            value={categoryFilter}
            onChange={setCategoryFilter}
            options={CATEGORY_OPTIONS}
          />
          <FilterSelect
            label="Owned"
            value={ownedFilter}
            onChange={setOwnedFilter}
            options={OWNED_OPTIONS}
          />
          <label className="flex items-center gap-1.5 text-xs text-neutral-500">
            Set code
            <input
              type="text"
              value={setCodeInput}
              onChange={(e) => setSetCodeInput(e.target.value)}
              placeholder="OP01"
              className="w-20 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200 placeholder:text-neutral-600"
            />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-neutral-500">
            Rarity
            <input
              type="text"
              value={rarityInput}
              onChange={(e) => setRarityInput(e.target.value)}
              placeholder="L"
              className="w-16 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200 placeholder:text-neutral-600"
            />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-neutral-500">
            Min score
            <input
              type="number"
              min={0}
              max={100}
              value={minScoreInput}
              onChange={(e) => setMinScoreInput(e.target.value)}
              placeholder="0"
              className="w-16 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200 placeholder:text-neutral-600"
            />
          </label>
          <FilterSelect
            label="Limit"
            value={String(limit)}
            onChange={(v) => setLimit(Number(v))}
            options={LIMIT_OPTIONS.map((n) => ({ value: String(n), label: String(n) }))}
          />
          <FilterSelect
            label="Tag"
            value={tagFilter}
            onChange={setTagFilter}
            options={tagOptions}
          />
          <FilterSelect
            label="Group"
            value={groupFilter}
            onChange={setGroupFilter}
            options={groupOptions}
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

        {status === "loading" && <LoadingState>Loading opportunities…</LoadingState>}

        {status === "error" && (
          <ErrorState>Failed to load opportunities from the API.</ErrorState>
        )}

        {status === "ready" && opportunities.length === 0 && (
          <EmptyState>No ranked opportunities found</EmptyState>
        )}

        {status === "ready" && opportunities.length > 0 && filteredOpportunities.length === 0 && (
          <EmptyState>No opportunities match the selected filters.</EmptyState>
        )}

        {status === "ready" && filteredOpportunities.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-neutral-800">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                  <th className="px-2 py-1.5 font-medium">Score</th>
                  <th className="px-2 py-1.5 font-medium">Category</th>
                  <th className="px-2 py-1.5 font-medium">Status</th>
                  <th className="px-2 py-1.5 font-medium">Signal type</th>
                  <th className="px-2 py-1.5 font-medium">Code</th>
                  <th className="px-2 py-1.5 font-medium">Name</th>
                  <th className="px-2 py-1.5 font-medium">Set</th>
                  <th className="px-2 py-1.5 font-medium">Rarity</th>
                  <th className="px-2 py-1.5 font-medium">Owned</th>
                  <th className="px-2 py-1.5 font-medium">Wishlist</th>
                  <th className="px-2 py-1.5 font-medium">Tags</th>
                  <th className="px-2 py-1.5 font-medium">Groups</th>
                  <th className="px-2 py-1.5 font-medium">Grading</th>
                  <th className="px-2 py-1.5 font-medium">Message</th>
                  <th className="px-2 py-1.5 font-medium">Seen</th>
                  <th className="px-2 py-1.5 font-medium">Last seen</th>
                  <th className="px-2 py-1.5 font-medium">Score reasons</th>
                  <th className="px-2 py-1.5 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredOpportunities.map((opp) => {
                  const isPending = pendingActionId === opp.event_id;
                  return (
                    <tr
                      key={opp.event_id}
                      className={`border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60 ${
                        opp.wishlist_target_hit ? "bg-emerald-500/[0.04]" : ""
                      }`}
                    >
                      <td className="px-2 py-1.5">
                        <span className={`text-base font-bold ${scoreColor(opp.score)}`}>
                          {opp.score}
                        </span>
                      </td>
                      <td className="px-2 py-1.5">
                        <OpportunityCategoryBadge category={opp.category} />
                      </td>
                      <td className="px-2 py-1.5">
                        <MarketSignalEventStatusBadge status={opp.status} />
                      </td>
                      <td className="px-2 py-1.5 text-neutral-300">{opp.signal_type}</td>
                      <td className="px-2 py-1.5 font-mono text-neutral-400">
                        {opp.card_id !== null ? (
                          <Link href={`/cards/${opp.card_id}`} className="hover:text-sky-400">
                            {opp.card_code ?? "—"}
                          </Link>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-2 py-1.5 font-medium text-neutral-100">
                        {opp.card_id !== null ? cardDisplayName(opp) : "—"}
                      </td>
                      <td className="px-2 py-1.5 text-neutral-400">{opp.set_code ?? "—"}</td>
                      <td className="px-2 py-1.5">
                        {opp.rarity ? <RarityBadge rarity={opp.rarity} /> : "—"}
                      </td>
                      <td className="px-2 py-1.5 text-neutral-200">
                        {opp.owned_quantity > 0 ? (
                          <Link href="/collection" className="hover:text-sky-400">
                            {opp.owned_quantity}
                          </Link>
                        ) : (
                          0
                        )}
                      </td>
                      <td className="px-2 py-1.5">
                        {opp.wishlist_item_id !== null ? (
                          <div className="flex flex-col gap-0.5">
                            <div className="flex items-center gap-1">
                              {opp.wishlist_priority && (
                                <WishlistPriorityBadge priority={opp.wishlist_priority} />
                              )}
                              {opp.wishlist_target_hit && (
                                <span className="rounded px-1.5 py-0.5 text-[10px] font-medium text-emerald-300 ring-1 ring-inset ring-emerald-500/30">
                                  target hit
                                </span>
                              )}
                            </div>
                            {opp.wishlist_target_buy_price_jpy !== null && (
                              <span className="text-[10px] text-neutral-500">
                                target {formatJpy(opp.wishlist_target_buy_price_jpy)}
                              </span>
                            )}
                          </div>
                        ) : (
                          <span className="text-neutral-600">—</span>
                        )}
                      </td>
                      <td className="px-2 py-1.5">
                        {opp.tags.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {opp.tags.map((tag) => (
                              <CollectorTagBadge key={tag.id} tag={tag} />
                            ))}
                          </div>
                        ) : (
                          <span className="text-neutral-600">—</span>
                        )}
                      </td>
                      <td className="px-2 py-1.5">
                        {opp.groups.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {opp.groups.map((group) => (
                              <CollectorGroupLabel key={group.id} group={group} />
                            ))}
                          </div>
                        ) : (
                          <span className="text-neutral-600">—</span>
                        )}
                      </td>
                      <td className="px-2 py-1.5">
                        {opp.grading.has_grading_submission ? (
                          <div className="flex flex-col gap-0.5">
                            <GradingStatusBadge status={opp.grading.latest_status ?? "planned"} />
                            {opp.category === "sell" &&
                              opp.grading.latest_status &&
                              ["submitted", "grading", "shipped_back"].includes(
                                opp.grading.latest_status,
                              ) && (
                                <span className="text-[10px] text-amber-400">
                                  away for grading
                                </span>
                              )}
                          </div>
                        ) : (
                          <span className="text-neutral-600">—</span>
                        )}
                      </td>
                      <td className="max-w-[16rem] px-2 py-1.5 text-neutral-400">
                        {opp.message ?? "—"}
                      </td>
                      <td className="px-2 py-1.5">
                        <span
                          className={`font-semibold ${
                            opp.seen_count > 1 ? "text-amber-300" : "text-neutral-300"
                          }`}
                        >
                          {opp.seen_count}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-2 py-1.5 text-neutral-400">
                        {formatDateTime(opp.last_seen_at)}
                      </td>
                      <td className="min-w-[12rem] max-w-[16rem] px-2 py-1.5 text-neutral-500">
                        {opp.score_reasons.length > 0 ? opp.score_reasons.join("; ") : "—"}
                      </td>
                      <td className="px-2 py-1.5">
                        <div className="flex flex-wrap gap-2">
                          {opp.card_id !== null && (
                            <Link
                              href={`/cards/${opp.card_id}`}
                              className="text-xs font-medium text-neutral-400 hover:text-neutral-200"
                            >
                              Card
                            </Link>
                          )}
                          <Link
                            href="/market/signal-events"
                            className="text-xs font-medium text-neutral-400 hover:text-neutral-200"
                          >
                            Event
                          </Link>
                          {opp.status !== "watching" && (
                            <button
                              onClick={() => handleWatch(opp)}
                              disabled={isPending}
                              className="text-xs font-medium text-violet-400 hover:text-violet-300 disabled:opacity-50"
                            >
                              Watch
                            </button>
                          )}
                          {opp.status !== "dismissed" && (
                            <button
                              onClick={() => handleDismiss(opp)}
                              disabled={isPending}
                              className="text-xs font-medium text-neutral-400 hover:text-neutral-200 disabled:opacity-50"
                            >
                              Dismiss
                            </button>
                          )}
                          {opp.status !== "resolved" && (
                            <button
                              onClick={() => handleResolve(opp)}
                              disabled={isPending}
                              className="text-xs font-medium text-emerald-400 hover:text-emerald-300 disabled:opacity-50"
                            >
                              Resolve
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

        {status === "ready" && summary && (
          <div className="mt-3">
            <PaginationControls
              offset={offset}
              limit={limit}
              total={summary.total_opportunities}
              onOffsetChange={setOffset}
            />
          </div>
        )}
      </main>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
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
