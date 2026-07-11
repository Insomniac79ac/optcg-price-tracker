"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { RarityBadge } from "@/components/RarityBadge";
import { SeverityBadge } from "@/components/SeverityBadge";
import {
  MARKET_SIGNAL_TYPES,
  type Card,
  type MarketSignal,
  type MarketSignalsSummary,
  fetchCards,
  fetchMarketSignals,
} from "@/lib/api";
import { cardDisplayName, formatJpy, formatSignedJpy, formatSignedPct } from "@/lib/format";

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

type TabKey = "all" | "buy" | "sell" | "momentum" | "drops" | "data_quality" | "owned";

const TAB_OPTIONS: { key: TabKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "buy", label: "Buy opportunities" },
  { key: "sell", label: "Sell opportunities" },
  { key: "momentum", label: "Momentum" },
  { key: "drops", label: "Drops" },
  { key: "data_quality", label: "Data quality" },
  { key: "owned", label: "Owned cards" },
];

function suggestedActionGroup(action: string): Exclude<TabKey, "all"> | null {
  switch (action) {
    case "review_buy_opportunity":
      return "buy";
    case "review_sell_opportunity":
      return "sell";
    case "monitor_momentum":
      return "momentum";
    case "monitor_drop":
      return "drops";
    case "review_mapping":
    case "update_prices":
      return "data_quality";
    case "add_collection_target":
      return "owned";
    default:
      return null; // "none" -> All tab only
  }
}

const LIMIT_OPTIONS = [25, 50, 100] as const;

const ALL_OPTION = { value: "", label: "All" };
const SOURCE_OPTIONS = [
  { value: "", label: "All sources" },
  { value: "yuyutei", label: "Yuyu-Tei" },
  { value: "snkrdunk", label: "SNKRDUNK" },
];
const OWNED_OPTIONS = [
  { value: "", label: "All" },
  { value: "true", label: "Owned only" },
  { value: "false", label: "Unowned only" },
];

function formatPriceOrMissing(value: number | null) {
  if (value === null) {
    return <span className="italic text-neutral-600">missing</span>;
  }
  return <span>{formatJpy(value)}</span>;
}

function formatKeyMetric(signal: MarketSignal): string {
  const { change_pct, spread_pct, gap_pct, gap_jpy } = signal.metrics;
  if (change_pct !== null) return formatSignedPct(change_pct);
  if (spread_pct !== null) return `${spread_pct.toFixed(2)}% spread`;
  if (gap_pct !== null) {
    const jpyPart = gap_jpy !== null ? ` (${formatSignedJpy(gap_jpy)})` : "";
    return `${formatSignedPct(gap_pct)}${jpyPart}`;
  }
  return "—";
}

function topSignalType(bySignalType: Record<string, number>): string {
  let best: string | null = null;
  let bestCount = 0;
  for (const [type, count] of Object.entries(bySignalType)) {
    if (count > bestCount) {
      best = type;
      bestCount = count;
    }
  }
  if (best === null) return "—";
  return `${SIGNAL_TYPE_LABELS[best] ?? best} (${bestCount})`;
}

export default function MarketSignalsPage() {
  const [signals, setSignals] = useState<MarketSignal[]>([]);
  const [summary, setSummary] = useState<MarketSignalsSummary | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");

  const [allCards, setAllCards] = useState<Card[]>([]);

  const [signalTypeFilter, setSignalTypeFilter] = useState("");
  const [setCodeFilter, setSetCodeFilter] = useState("");
  const [rarityFilter, setRarityFilter] = useState("");
  const [ownedFilter, setOwnedFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [limit, setLimit] = useState<number>(100);

  const [activeTab, setActiveTab] = useState<TabKey>("all");

  useEffect(() => {
    fetchCards()
      .then(setAllCards)
      .catch(() => setAllCards([]));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");

    fetchMarketSignals({
      signal_type: signalTypeFilter || undefined,
      set_code: setCodeFilter || undefined,
      rarity: rarityFilter || undefined,
      source: sourceFilter || undefined,
      owned: ownedFilter === "" ? undefined : ownedFilter === "true",
      limit,
    })
      .then((data) => {
        if (cancelled) return;
        setSignals(data.signals);
        setSummary(data.summary);
        setStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, [signalTypeFilter, setCodeFilter, rarityFilter, ownedFilter, sourceFilter, limit]);

  const setCodeOptions = useMemo(() => {
    const values = Array.from(new Set(allCards.map((c) => c.set_code))).sort();
    return [ALL_OPTION, ...values.map((v) => ({ value: v, label: v }))];
  }, [allCards]);

  const rarityOptions = useMemo(() => {
    const values = Array.from(new Set(allCards.map((c) => c.rarity))).sort();
    return [ALL_OPTION, ...values.map((v) => ({ value: v, label: v }))];
  }, [allCards]);

  const tabCounts = useMemo(() => {
    const counts: Record<TabKey, number> = {
      all: signals.length,
      buy: 0,
      sell: 0,
      momentum: 0,
      drops: 0,
      data_quality: 0,
      owned: 0,
    };
    for (const signal of signals) {
      const group = suggestedActionGroup(signal.suggested_action);
      if (group) counts[group] += 1;
    }
    return counts;
  }, [signals]);

  const visibleSignals = useMemo(() => {
    if (activeTab === "all") return signals;
    return signals.filter((s) => suggestedActionGroup(s.suggested_action) === activeTab);
  }, [signals, activeTab]);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-4 flex items-baseline justify-between">
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-semibold text-neutral-100">
              Market signals
            </h1>
            <Link
              href="/market/signal-events"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Review signal events
            </Link>
            <Link
              href="/market/opportunities"
              className="text-xs text-sky-400 underline decoration-sky-800 underline-offset-2 hover:text-sky-300"
            >
              Ranked opportunities
            </Link>
          </div>
          {status === "ready" && (
            <span className="text-sm text-neutral-500">
              {visibleSignals.length} of {signals.length} signal
              {signals.length === 1 ? "" : "s"}
            </span>
          )}
        </div>

        {summary && (
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <StatCard label="Total signals" value={summary.total_signals} />
            <StatCard label="Market signals" value={summary.market_signal_count} />
            <StatCard label="Owned signals" value={summary.owned_signal_count} />
            <StatCard
              label="Data quality signals"
              value={summary.data_quality_signal_count}
            />
            <StatCard
              label="Top signal type"
              value={topSignalType(summary.by_signal_type)}
            />
          </div>
        )}

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <FilterSelect
            label="Signal type"
            value={signalTypeFilter}
            onChange={setSignalTypeFilter}
            options={[
              ALL_OPTION,
              ...MARKET_SIGNAL_TYPES.map((t) => ({
                value: t,
                label: SIGNAL_TYPE_LABELS[t] ?? t,
              })),
            ]}
          />
          <FilterSelect
            label="Set"
            value={setCodeFilter}
            onChange={setSetCodeFilter}
            options={setCodeOptions}
          />
          <FilterSelect
            label="Rarity"
            value={rarityFilter}
            onChange={setRarityFilter}
            options={rarityOptions}
          />
          <FilterSelect
            label="Owned"
            value={ownedFilter}
            onChange={setOwnedFilter}
            options={OWNED_OPTIONS}
          />
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

        <div className="mb-4 flex flex-wrap gap-1">
          {TAB_OPTIONS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`rounded px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                activeTab === tab.key
                  ? "bg-neutral-100 text-neutral-900 ring-neutral-100"
                  : "bg-neutral-900 text-neutral-400 ring-neutral-800 hover:text-neutral-100"
              }`}
            >
              {tab.label}
              <span className="ml-1 text-[11px] opacity-70">
                {tabCounts[tab.key]}
              </span>
            </button>
          ))}
        </div>

        {status === "loading" && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            Loading market signals…
          </div>
        )}

        {status === "error" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Failed to load market signals from the API.
          </div>
        )}

        {status === "ready" && visibleSignals.length === 0 && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            No market signals found
          </div>
        )}

        {status === "ready" && visibleSignals.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-neutral-800">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
                  <th className="px-2 py-1.5 font-medium">Signal type</th>
                  <th className="px-2 py-1.5 font-medium">Severity</th>
                  <th className="px-2 py-1.5 font-medium">Code</th>
                  <th className="px-2 py-1.5 font-medium">Name</th>
                  <th className="px-2 py-1.5 font-medium">Set</th>
                  <th className="px-2 py-1.5 font-medium">Rarity</th>
                  <th className="px-2 py-1.5 font-medium">Owned</th>
                  <th className="px-2 py-1.5 font-medium">Yuyu-Tei sell</th>
                  <th className="px-2 py-1.5 font-medium">Yuyu-Tei buy</th>
                  <th className="px-2 py-1.5 font-medium">SNKRDUNK floor</th>
                  <th className="px-2 py-1.5 font-medium">Key metric</th>
                  <th className="px-2 py-1.5 font-medium">Suggested action</th>
                  <th className="px-2 py-1.5 font-medium">Message</th>
                </tr>
              </thead>
              <tbody>
                {visibleSignals.map((signal, idx) => (
                  <tr
                    key={`${signal.card_id}-${signal.signal_type}-${idx}`}
                    className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                  >
                    <td className="px-2 py-1.5 text-neutral-300">
                      {SIGNAL_TYPE_LABELS[signal.signal_type] ?? signal.signal_type}
                    </td>
                    <td className="px-2 py-1.5">
                      <SeverityBadge severity={signal.severity} />
                    </td>
                    <td className="px-2 py-1.5 font-mono text-neutral-400">
                      <Link
                        href={`/cards/${signal.card_id}`}
                        className="hover:text-sky-400"
                      >
                        {signal.card_code}
                      </Link>
                    </td>
                    <td className="px-2 py-1.5 font-medium text-neutral-100">
                      {cardDisplayName(signal)}
                    </td>
                    <td className="px-2 py-1.5 text-neutral-400">
                      {signal.set_code}
                    </td>
                    <td className="px-2 py-1.5">
                      <RarityBadge rarity={signal.rarity} />
                    </td>
                    <td className="px-2 py-1.5 text-neutral-200">
                      {signal.owned_quantity > 0 ? (
                        <Link href="/collection" className="hover:text-sky-400">
                          {signal.owned_quantity}
                        </Link>
                      ) : (
                        0
                      )}
                    </td>
                    <td className="px-2 py-1.5 text-neutral-200">
                      {formatPriceOrMissing(signal.latest_prices.yuyutei_sell)}
                    </td>
                    <td className="px-2 py-1.5 text-neutral-200">
                      {formatPriceOrMissing(signal.latest_prices.yuyutei_buy)}
                    </td>
                    <td className="px-2 py-1.5 text-neutral-200">
                      {formatPriceOrMissing(signal.latest_prices.snkrdunk_floor)}
                    </td>
                    <td className="px-2 py-1.5 text-neutral-200">
                      {formatKeyMetric(signal)}
                    </td>
                    <td className="px-2 py-1.5">
                      {signal.suggested_action === "update_prices" ? (
                        <Link
                          href="/admin/refresh-runs"
                          className="text-sky-400 hover:text-sky-300"
                        >
                          {SUGGESTED_ACTION_LABELS[signal.suggested_action]}
                        </Link>
                      ) : (
                        <span className="text-neutral-300">
                          {SUGGESTED_ACTION_LABELS[signal.suggested_action] ??
                            signal.suggested_action}
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-1.5 text-neutral-400">
                      {signal.message}
                    </td>
                  </tr>
                ))}
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
