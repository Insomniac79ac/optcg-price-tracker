"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { PriceChart } from "@/components/PriceChart";
import { RarityBadge } from "@/components/RarityBadge";
import { StockStatusBadge } from "@/components/StockStatusBadge";
import {
  type Card,
  type PriceObservation,
  fetchCard,
  fetchCardPrices,
} from "@/lib/api";
import { cardDisplayName, formatDateTime, formatJpy } from "@/lib/format";

type Status = "loading" | "error" | "ready";

export default function CardDetailPage() {
  const params = useParams<{ id: string }>();
  const cardId = params.id;

  const [card, setCard] = useState<Card | null>(null);
  const [prices, setPrices] = useState<PriceObservation[]>([]);
  const [status, setStatus] = useState<Status>("loading");

  useEffect(() => {
    let cancelled = false;

    Promise.all([fetchCard(cardId), fetchCardPrices(cardId)])
      .then(([cardData, priceData]) => {
        if (cancelled) return;
        setCard(cardData);
        setPrices(priceData);
        setStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, [cardId]);

  const latestFirst = prices
    .slice()
    .sort(
      (a, b) =>
        new Date(b.observed_at).getTime() - new Date(a.observed_at).getTime(),
    );

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Link
          href="/dashboard"
          className="mb-4 inline-block text-sm text-neutral-400 hover:text-neutral-100"
        >
          ← Back to dashboard
        </Link>

        {status === "loading" && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
            Loading card…
          </div>
        )}

        {status === "error" && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-8 text-center text-sm text-rose-300">
            Failed to load this card from the API.
          </div>
        )}

        {status === "ready" && card && (
          <div className="space-y-6">
            <div className="flex flex-col gap-4 rounded-lg border border-neutral-800 bg-neutral-900 p-4 sm:flex-row">
              {card.image_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={card.image_url}
                  alt={cardDisplayName(card)}
                  className="h-48 w-36 rounded-md border border-neutral-800 object-cover"
                />
              )}
              <div className="flex-1 space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-xl font-semibold text-neutral-100">
                    {cardDisplayName(card)}
                  </h1>
                  <RarityBadge rarity={card.rarity} />
                </div>
                {card.name_en && card.name_jp && (
                  <p className="text-sm text-neutral-500">{card.name_jp}</p>
                )}
                <dl className="grid grid-cols-2 gap-x-6 gap-y-1 pt-2 text-sm sm:grid-cols-4">
                  <div>
                    <dt className="text-xs uppercase text-neutral-500">
                      Code
                    </dt>
                    <dd className="font-mono text-neutral-200">
                      {card.card_code}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase text-neutral-500">Set</dt>
                    <dd className="text-neutral-200">{card.set_code}</dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase text-neutral-500">
                      Variant
                    </dt>
                    <dd className="text-neutral-200">
                      {card.variant ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase text-neutral-500">
                      Language
                    </dt>
                    <dd className="uppercase text-neutral-200">
                      {card.language}
                    </dd>
                  </div>
                </dl>
              </div>
            </div>

            <div>
              <h2 className="mb-2 text-sm font-semibold text-neutral-100">
                Price history
              </h2>
              <PriceChart observations={prices} />
            </div>

            <div>
              <h2 className="mb-2 text-sm font-semibold text-neutral-100">
                Price observations
              </h2>
              {latestFirst.length === 0 ? (
                <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center text-sm text-neutral-500">
                  No price observations yet.
                </div>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-neutral-800">
                  <table className="w-full border-collapse text-sm">
                    <thead>
                      <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wide text-neutral-500">
                        <th className="px-3 py-2 font-medium">Observed at</th>
                        <th className="px-3 py-2 font-medium">Source</th>
                        <th className="px-3 py-2 font-medium">Type</th>
                        <th className="px-3 py-2 font-medium text-right">
                          Price
                        </th>
                        <th className="px-3 py-2 font-medium">Condition</th>
                        <th className="px-3 py-2 font-medium">Stock</th>
                        <th className="px-3 py-2 font-medium text-right">
                          Listings
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {latestFirst.map((obs) => (
                        <tr
                          key={obs.id}
                          className="border-b border-neutral-900 last:border-0 hover:bg-neutral-900/60"
                        >
                          <td className="px-3 py-2 text-neutral-300">
                            {formatDateTime(obs.observed_at)}
                          </td>
                          <td className="px-3 py-2 text-neutral-400">
                            Source #{obs.source_id}
                          </td>
                          <td className="px-3 py-2 text-neutral-400">
                            {obs.price_type}
                          </td>
                          <td className="px-3 py-2 text-right text-neutral-200">
                            {formatJpy(obs.price_jpy)}
                          </td>
                          <td className="px-3 py-2 text-neutral-400">
                            {obs.condition_label ?? "—"}
                          </td>
                          <td className="px-3 py-2">
                            <StockStatusBadge status={obs.stock_status} />
                          </td>
                          <td className="px-3 py-2 text-right text-neutral-400">
                            {obs.listing_count ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
