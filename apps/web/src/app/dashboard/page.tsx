"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { PriceTypeBadge } from "@/components/PriceTypeBadge";
import { RarityBadge } from "@/components/RarityBadge";
import { SourceBadge } from "@/components/SourceBadge";
import {
  type Card,
  type MarketMover,
  fetchCards,
  fetchMarketMovers,
} from "@/lib/api";
import { cardDisplayName, formatJpy } from "@/lib/format";

const SOURCE_OPTIONS = [
  { value: "", label: "All sources" },
  { value: "yuyutei", label: "Yuyu-Tei" },
  { value: "snkrdunk", label: "SNKRDUNK" },
];

const PRICE_TYPE_OPTIONS = [
  { value: "", label: "All price types" },
  { value: "sell", label: "Sell" },
  { value: "buy", label: "Buy" },
  { value: "floor", label: "Floor" },
  { value: "sold", label: "Sold" },
];

export default function DashboardPage() {
  const [movers, setMovers] = useState<MarketMover[]>([]);
  const [allCards, setAllCards] = useState<Card[]>([]);
  const [status, setStatus] = useState<"loading" | "error" | "ready">(
    "loading",
  );

  const [sourceFilter, setSourceFilter] = useState("");
  const [priceTypeFilter, setPriceTypeFilter] = useState("");
  const [rarityFilter, setRarityFilter] = useState("");
  const [variantFilter, setVariantFilter] = useState("");

  useEffect(() => {
    fetchCards()
      .then(setAllCards)
      .catch(() => setAllCards([]));
  }, []);

  useEffect(() => {
    let cancelled = false;

    fetchMarketMovers({
      source: sourceFilter || undefined,
      price_type: priceTypeFilter || undefined,
      rarity: rarityFilter || undefined,
      variant: variantFilter || undefined,
      limit: 200,
    })
      .then((data) => {
        if (cancelled) return;
        setMovers(data);
        setStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, [sourceFilter, priceTypeFilter, rarityFilter, variantFilter]);

  const rarityOptions = useMemo(() => {
    const values = Array.from(new Set(allCards.map((c) => c.rarity))).sort();
    return [{ value: "", label: "All rarities" }, ...values.map((v) => ({ value: v, label: v }))];
  }, [allCards]);

  const variantOptions = useMemo(() => {
    const values = Array.from(
      new Set(allCards.map((c) => c.variant).filter((v): v is string => !!v)),
    ).sort();
    return [
      { value: "", label: "All variants" },
      ...values.map((v) => ({ value: v, label: v })),
    ];
  }, [allCards]);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-4 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">Market</h1>
          {status === "ready" && (
            <span className="text-sm text-neutral-500">
              {movers.length} card{movers.length === 1 ? "" : "s"}
            </span>
          )}
        </div>

        <div className="mb-4 flex gap-3 text-xs text-neutral-500">
          <Link
            href="/collection"
            className="underline decoration-neutral-700 underline-offset-2 hover:text-neutral-100"
          >
            Collection
          </Link>
          <Link
            href="/wishlist"
            className="underline decoration-neutral-700 underline-offset-2 hover:text-neutral-100"
          >
            Wishlist
          </Link>
          <Link
            href="/market/signals"
            className="underline decoration-neutral-700 underline-offset-2 hover:text-neutral-100"
          >
            Market signals
          </Link>
          <Link
            href="/market/signal-events"
            className="underline decoration-neutral-700 underline-offset-2 hover:text-neutral-100"
          >
            Signal events
          </Link>
          <Link
            href="/market/opportunities"
            className="underline decoration-neutral-700 underline-offset-2 hover:text-neutral-100"
          >
            Opportunities
          </Link>
          <Link
            href="/market/report"
            className="underline decoration-neutral-700 underline-offset-2 hover:text-neutral-100"
          >
            Market report
          </Link>
          <Link
            href="/admin/refresh-runs"
            className="underline decoration-neutral-700 underline-offset-2 hover:text-neutral-100"
          >
            Refresh runs
          </Link>
          <Link
            href="/admin/snkrdunk-candidates"
            className="underline decoration-neutral-700 underline-offset-2 hover:text-neutral-100"
          >
            SNKRDUNK candidates
          </Link>
          <Link
            href="/admin/alerts"
            className="underline decoration-neutral-700 underline-offset-2 hover:text-neutral-100"
          >
            Alerts
          </Link>
          <Link
            href="/admin/card-audit"
            className="underline decoration-neutral-700 underline-offset-2 hover:text-neutral-100"
          >
            Card audit
          </Link>
        </div>

        <div className="mb-4 flex flex-wrap gap-2">
          <Select
            value={sourceFilter}
            onChange={setSourceFilter}
            options={SOURCE_OPTIONS}
          />
          <Select
            value={priceTypeFilter}
            onChange={setPriceTypeFilter}
            options={PRICE_TYPE_OPTIONS}
          />
          <Select
            value={rarityFilter}
            onChange={setRarityFilter}
            options={rarityOptions}
          />
          <Select
            value={variantFilter}
            onChange={setVariantFilter}
            options={variantOptions}
          />
        </div>

        {status === "loading" && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            Loading market data…
          </div>
        )}

        {status === "error" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Failed to load market data from the API. Is the backend running?
          </div>
        )}

        {status === "ready" && movers.length === 0 && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            No cards match these filters.
          </div>
        )}

        {status === "ready" && movers.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-neutral-800">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wide text-neutral-500">
                  <th className="px-3 py-2 font-medium">Card</th>
                  <th className="px-3 py-2 font-medium">Code</th>
                  <th className="px-3 py-2 font-medium">Rarity</th>
                  <th className="px-3 py-2 font-medium">Variant</th>
                  <th className="px-3 py-2 font-medium">Prices</th>
                </tr>
              </thead>
              <tbody>
                {movers.map((mover) => (
                  <tr
                    key={mover.card_id}
                    className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                  >
                    <td className="px-3 py-2">
                      <Link
                        href={`/cards/${mover.card_id}`}
                        className="font-medium text-neutral-100 hover:text-sky-400"
                      >
                        {cardDisplayName(mover)}
                      </Link>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-neutral-400">
                      {mover.card_code}
                    </td>
                    <td className="px-3 py-2">
                      <RarityBadge rarity={mover.rarity} />
                    </td>
                    <td className="px-3 py-2 text-neutral-400">
                      {mover.variant ?? "—"}
                    </td>
                    <td className="px-3 py-2">
                      {mover.latest_prices.length === 0 ? (
                        <span className="text-neutral-600">
                          No price data
                        </span>
                      ) : (
                        <div className="flex flex-wrap gap-2">
                          {mover.latest_prices.map((price) => (
                            <div
                              key={`${price.source}-${price.price_type}-${price.condition_label ?? ""}`}
                              className="flex items-center gap-1.5 rounded border border-neutral-800 bg-neutral-900 px-2 py-1"
                            >
                              <SourceBadge source={price.source} />
                              <PriceTypeBadge priceType={price.price_type} />
                              <span className="font-medium text-neutral-200">
                                {formatJpy(price.price_jpy)}
                              </span>
                              {price.condition_label && (
                                <span className="text-xs text-neutral-500">
                                  {price.condition_label}
                                </span>
                              )}
                              {price.listing_count !== null && (
                                <span className="text-xs text-neutral-500">
                                  ×{price.listing_count}
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
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

function Select({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
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
  );
}
