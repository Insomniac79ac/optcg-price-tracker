"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { fetchCards, fetchCollectionValuation, type Card, type PortfolioValuationItem } from "@/lib/api";
import { cardDisplayName } from "@/lib/format";
import { CardVaultTile } from "./CardVaultTile";

const HIGHLIGHT_COUNT = 4;

/** Top-N owned cards by current (raw market) value, for /dashboard - same
 * "self-contained, independently-fetching, quiet if nothing" pattern as
 * PinnedViewsSection, not part of the DashboardOverview/widget system (this
 * isn't a customizable/hideable widget, just a shortcut into the full
 * /collection/vault grid). Never recomputes valuation - reads market_floor_
 * value_jpy straight off /collection/valuation, same source /collection and
 * /collection/vault both already use. */
export function VaultHighlightsSection() {
  const [items, setItems] = useState<PortfolioValuationItem[] | null>(null);
  const [cards, setCards] = useState<Card[]>([]);

  useEffect(() => {
    fetchCollectionValuation("raw_market")
      .then((data) => setItems(data.items))
      .catch(() => setItems([]));
    fetchCards()
      .then(setCards)
      .catch(() => setCards([]));
  }, []);

  if (!items || items.length === 0) return null;

  const cardsById = new Map(cards.map((c) => [c.id, c]));

  const top = [...items]
    .sort(
      (a, b) =>
        (b.valuations.market_floor_value_jpy ?? -Infinity) -
        (a.valuations.market_floor_value_jpy ?? -Infinity),
    )
    .slice(0, HIGHLIGHT_COUNT);

  return (
    <div className="mb-6">
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-text-primary">Vault Highlights</h2>
        <Link href="/collection/vault" className="text-xs text-sky-400 hover:text-sky-300">
          View vault →
        </Link>
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {top.map((v) => (
          <CardVaultTile
            key={v.collection_item_id}
            cardId={v.card_id}
            cardCode={v.card_code}
            name={cardDisplayName(v)}
            imageUrl={cardsById.get(v.card_id)?.image_url ?? null}
            rarity={v.rarity}
            variant={v.variant}
            setCode={v.set_code}
            valueJpy={v.valuations.market_floor_value_jpy}
            mode="raw_market"
            density="compact"
          />
        ))}
      </div>
    </div>
  );
}
