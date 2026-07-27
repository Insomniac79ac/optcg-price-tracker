"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { CardGrid } from "@/components/ui/CardGrid";
import { CardGridSkeleton } from "@/components/ui/CardGridSkeleton";
import { CollectorCardTile } from "@/components/ui/CollectorCardTile";
import { CollectorEmptyState } from "@/components/ui/CollectorEmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { ErrorState } from "@/components/StateBlocks";
import { type CardCatalogueItem, fetchCardsCatalogue } from "@/lib/api";

const DISPLAY_LIMIT = 60;

/** The public Market Index page (collector-first redesign audit, Phase 8) -
 * replaces the old "Market movers" page, which was a dense per-source price
 * table with a row of plain-text links straight to internal/admin tooling
 * (Dashboard, Refresh runs, SNKRDUNK candidates, Card audit, ...) sitting on
 * a page every anonymous visitor could reach. That page's data (per-source
 * price + `GET /market/movers`) still exists and is unchanged - this page
 * just no longer uses it, in favor of the same `GET /cards/catalogue` (and
 * therefore the same computed Market Index) the /cards page and Discover
 * already use, sorted by index value so the cards with a real number lead.
 *
 * This page explains the Market Index (what it is, its sources, what full
 * vs. limited coverage and a listing-fallback mean, and that staging prices
 * are mock data) and then shows it applied to real cards - deliberately
 * never framed as a buy/sell recommendation or trading signal (see
 * docs/market_index.md "Market Index wording"). The actual calculation
 * (app.services.market_index) is unchanged by this page. */
export default function MarketIndexPage() {
  const [items, setItems] = useState<CardCatalogueItem[]>([]);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    fetchCardsCatalogue({ sort: "index_desc", limit: DISPLAY_LIMIT })
      .then((data) => {
        if (cancelled) return;
        setItems(data.items);
        setStatus("ready");
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <PageHeader
          title="Market Index"
          description="A reference price per card, drawn from Yuyu-Tei and SNKRDUNK - not a buy or sell recommendation."
        />

        <div className="panel mb-6 grid gap-4 p-4 text-sm text-text-secondary sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-faint">
              What it is
            </div>
            <p>
              The median of eligible prices across every contributing source - one JPY figure per
              card, not a single source's price.
            </p>
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-faint">
              Contributing sources
            </div>
            <p>Yuyu-Tei (sell, dealer-buy) and SNKRDUNK (sold, floor listing) - see each card's own breakdown.</p>
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-faint">
              Coverage &amp; fallback
            </div>
            <p>
              <span className="font-medium text-text-primary">Full</span> means both sources have
              an eligible price right now. <span className="font-medium text-text-primary">Limited</span>{" "}
              means only one does, or a listing price is standing in for a missing sale/sell price.
            </p>
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-faint">
              Freshness
            </div>
            <p>
              Each card shows when its most recent source observation landed - a{" "}
              <span className="text-signal-warning">stale</span> badge means over 48 hours old.
            </p>
          </div>
        </div>

        <p className="mb-6 text-xs text-text-faint">
          Staging data - prices are from the mock price source (SCRAPING_MODE=mock), not live.
        </p>

        {status === "loading" && <CardGridSkeleton />}

        {status === "error" && (
          <ErrorState
            action={
              <button
                type="button"
                onClick={() => {
                  setStatus("loading");
                  fetchCardsCatalogue({ sort: "index_desc", limit: DISPLAY_LIMIT })
                    .then((data) => {
                      setItems(data.items);
                      setStatus("ready");
                    })
                    .catch(() => setStatus("error"));
                }}
                className="rounded-control border border-border-default px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary"
              >
                Retry
              </button>
            }
          >
            Failed to load the Market Index.
          </ErrorState>
        )}

        {status === "ready" && items.length === 0 && (
          <CollectorEmptyState title="No cards yet">
            The catalogue is empty right now.
          </CollectorEmptyState>
        )}

        {status === "ready" && items.length > 0 && (
          <>
            <CardGrid>
              {items.map((card) => (
                <CollectorCardTile key={card.id} card={card} />
              ))}
            </CardGrid>
            <p className="mt-6 text-xs text-text-muted">
              Looking for a specific card?{" "}
              <Link href="/cards" className="text-sky-400 hover:underline">
                Browse the full catalogue →
              </Link>
            </p>
          </>
        )}
      </main>
    </div>
  );
}
