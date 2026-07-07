"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { RarityBadge } from "@/components/RarityBadge";
import { StockStatusBadge } from "@/components/StockStatusBadge";
import { type Card, fetchCards } from "@/lib/api";
import { cardDisplayName, formatJpy } from "@/lib/format";

export default function DashboardPage() {
  const [cards, setCards] = useState<Card[]>([]);
  const [status, setStatus] = useState<"loading" | "error" | "ready">(
    "loading",
  );

  useEffect(() => {
    let cancelled = false;

    fetchCards()
      .then((data) => {
        if (cancelled) return;
        setCards(data);
        setStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <div className="mb-4 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-neutral-100">Cards</h1>
          {status === "ready" && (
            <span className="text-sm text-neutral-500">
              {cards.length} card{cards.length === 1 ? "" : "s"}
            </span>
          )}
        </div>

        {status === "loading" && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            Loading cards…
          </div>
        )}

        {status === "error" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Failed to load cards from the API. Is the backend running?
          </div>
        )}

        {status === "ready" && cards.length === 0 && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            No cards found.
          </div>
        )}

        {status === "ready" && cards.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-neutral-800">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wide text-neutral-500">
                  <th className="px-3 py-2 font-medium">Card</th>
                  <th className="px-3 py-2 font-medium">Code</th>
                  <th className="px-3 py-2 font-medium">Rarity</th>
                  <th className="px-3 py-2 font-medium">Variant</th>
                  <th className="px-3 py-2 font-medium">Lang</th>
                  <th className="px-3 py-2 font-medium text-right">
                    Latest price
                  </th>
                  <th className="px-3 py-2 font-medium">Source</th>
                  <th className="px-3 py-2 font-medium">Stock</th>
                </tr>
              </thead>
              <tbody>
                {cards.map((card) => (
                  <tr
                    key={card.id}
                    className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                  >
                    <td className="px-3 py-2">
                      <Link
                        href={`/cards/${card.id}`}
                        className="font-medium text-neutral-100 hover:text-sky-400"
                      >
                        {cardDisplayName(card)}
                      </Link>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-neutral-400">
                      {card.card_code}
                    </td>
                    <td className="px-3 py-2">
                      <RarityBadge rarity={card.rarity} />
                    </td>
                    <td className="px-3 py-2 text-neutral-400">
                      {card.variant ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-neutral-400 uppercase">
                      {card.language}
                    </td>
                    <td className="px-3 py-2 text-right text-neutral-300">
                      {formatJpy(card.latest_price_jpy)}
                    </td>
                    <td className="px-3 py-2 text-neutral-400">
                      {card.latest_source ?? "—"}
                    </td>
                    <td className="px-3 py-2">
                      <StockStatusBadge status={card.latest_stock_status} />
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
