"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CardImageFrame } from "@/components/ui/CardImageFrame";
import { formatJpy } from "@/lib/format";
import {
  basisLabel,
  cardBasisValue,
  fetchMarketCards,
  MARKET_CARD_LIMIT,
  type MarketBasis,
  type MarketOverviewParams,
} from "@/lib/marketAnalytics";
import { toPrintUiModel, type PrintCatalogueItem } from "@/lib/prints";

/** Catalogue navigation carries only filters that /cards supports. */
export function marketCatalogueHref(releaseId?: number, rarity?: string): string {
  const params = new URLSearchParams();
  if (releaseId !== undefined) params.set("release_product_id", String(releaseId));
  if (rarity) params.set("rarity", rarity);
  return `/cards${params.size ? `?${params}` : ""}`;
}

/** One bounded, server-selected cohort. Keep the basis and destination tagged
 * with its response so old cards cannot acquire new price labels on refresh. */
export function MarketCardsSection({
  selection,
  basis,
  ready,
  unavailable = false,
}: {
  selection: MarketOverviewParams;
  basis: MarketBasis | null;
  ready: boolean;
  unavailable?: boolean;
}) {
  const { priceBasis, release_product_id: releaseId, rarity, set: legacySet } = selection;
  const [attempt, setAttempt] = useState(0);
  const key = JSON.stringify([priceBasis, releaseId, rarity, legacySet, attempt]);
  const [settled, setSettled] = useState<{
    key: string;
    items: PrintCatalogueItem[] | null;
    basis: MarketBasis | null;
    href: string;
    failed: boolean;
  } | null>(null);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    const href = marketCatalogueHref(releaseId, rarity);
    fetchMarketCards({
      priceBasis,
      release_product_id: releaseId,
      rarity,
      ...(legacySet ? { set: legacySet } : {}),
    })
      .then((data) => {
        if (!data || !Array.isArray(data.items)) throw new Error("Invalid cards response");
        if (!cancelled) setSettled({ key, items: data.items, basis, href, failed: false });
      })
      .catch(() => {
        if (!cancelled) setSettled({ key, items: null, basis, href, failed: true });
      });
    return () => {
      cancelled = true;
    };
  }, [ready, key, priceBasis, releaseId, rarity, legacySet, basis]);

  const current = settled?.key === key ? settled : null;
  const showing = current ?? (settled && !settled.failed ? settled : null);
  const failed = unavailable || current?.failed;
  const loading = !failed && current === null;
  const href = showing?.href ?? marketCatalogueHref(releaseId, rarity);

  return (
    <section className="mt-8" aria-labelledby="market-cards-heading" data-testid="market-cards">
      <h2 id="market-cards-heading" className="font-display text-xl font-semibold text-text-primary sm:text-[23px]">
        Cards in this market
      </h2>
      <p className="mt-1 text-sm text-text-secondary">A few of the prints with usable prices in this view.</p>
      <div aria-busy={loading} className={`mt-4 ${loading && showing ? "opacity-60 transition-opacity motion-reduce:transition-none" : ""}`}>
        {failed ? (
          <div className="py-6 text-sm text-text-muted">
            <p>Cards for this view could not be loaded.</p>
            {!unavailable && <button type="button" onClick={() => setAttempt((n) => n + 1)} className="mt-2 min-h-11 rounded-control px-2 text-accent-teal hover:underline focus-visible:outline-2 focus-visible:outline-accent-teal">Retry cards</button>}
          </div>
        ) : !showing?.items ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6" role="status" aria-label="Loading cards in this market">
            {Array.from({ length: MARKET_CARD_LIMIT }, (_, i) => <div key={i} className="min-w-0"><div className="aspect-[63/88] rounded-panel bg-bg-elevated" /><div className="mt-3 h-20 rounded bg-bg-elevated" /></div>)}
          </div>
        ) : showing.items.length === 0 ? (
          <p className="py-8 text-sm text-text-muted">No cards currently have a usable price for this view.</p>
        ) : (
          <ul className="grid grid-cols-2 gap-x-3 gap-y-6 sm:grid-cols-3 lg:grid-cols-6" data-testid="market-cards-grid">
            {showing.items.map((item) => (
              <MarketCard key={item.card_print_id} item={item} basis={showing.basis} />
            ))}
          </ul>
        )}
      </div>
      <Link href={href} prefetch={false} className="mt-4 inline-flex min-h-11 items-center rounded-control text-sm font-medium text-accent-teal hover:underline focus-visible:outline-2 focus-visible:outline-accent-teal">
        Browse these cards →
      </Link>
    </section>
  );
}

function MarketCard({ item, basis }: { item: PrintCatalogueItem; basis: MarketBasis | null }) {
  const print = toPrintUiModel(item);
  const price = cardBasisValue(item, basis);
  return (
    <li className="min-w-0" data-testid="market-card">
      <Link href={`/prints/${print.cardPrintId}`} prefetch={false} className="group flex h-full min-w-0 flex-col rounded-panel focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-teal">
        <CardImageFrame
          imageUrl={print.imageUrl}
          alt={`${print.displayName} (${print.cardCode})`}
          cardCode={print.cardCode}
          rarity={print.rarity}
          setCode={print.releaseCode}
          size="full"
          padded
          geometry={print.imageGeometry}
        />
        <div className="flex flex-1 flex-col pt-2.5">
          <p className="truncate text-sm font-medium text-text-primary group-hover:text-accent-teal-hover">{print.displayName}</p>
          <p className="mt-1 text-xs text-text-secondary">{print.cardCode}</p>
          {(print.releaseCode || print.releaseProductId) && <p className="mt-1 text-xs text-text-muted">Found in {print.releaseCode ?? "Special product"}</p>}
          <div className="mt-auto pt-3">
            <p className="text-xs leading-relaxed text-text-muted">{basis ? basisLabel(basis) : "Market Index"}</p>
            <p className="mt-1 font-display text-lg font-semibold tabular-nums text-text-primary">{price === null ? "Unavailable" : formatJpy(price)}</p>
          </div>
        </div>
      </Link>
    </li>
  );
}
