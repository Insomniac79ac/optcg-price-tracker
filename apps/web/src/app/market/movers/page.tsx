"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { CardGrid } from "@/components/ui/CardGrid";
import { CardGridSkeleton } from "@/components/ui/CardGridSkeleton";
import { CollectorEmptyState } from "@/components/ui/CollectorEmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { PrintCardTile } from "@/components/ui/PrintCardTile";
import { ErrorState } from "@/components/StateBlocks";
import { fetchPrintCatalogue, toPrintUiModel, type PrintUiModel } from "@/lib/prints";

const DISPLAY_LIMIT = 60;

/** The public Market Index page (collector-first redesign audit, Phase 8) -
 * replaces the old "Market movers" page, which was a dense per-source price
 * table with a row of plain-text links straight to internal/admin tooling
 * (Dashboard, Refresh runs, SNKRDUNK candidates, Card audit, ...) sitting on
 * a page every anonymous visitor could reach.
 *
 * Now backed by `GET /prints?sort=index_desc`, the same print catalogue the
 * /cards page uses, rather than the legacy `GET /cards/catalogue`. That is
 * what lets every tile here link to /prints/{card_print_id}: the ranking is
 * over exact printings, each with its own print-scoped Market Index, so a
 * base and a parallel of one card rank independently instead of being merged
 * behind a single canonical row. The legacy catalogue carried no print
 * identity, so nothing on this page could have linked to an exact printing
 * without guessing which one it meant.
 *
 * The ordering is the API's own `index_desc` (index value descending, prints
 * with no index last - see services/api/app/services/print_catalogue.py). It
 * is a *ranking by current index value*, not price movement: the payload
 * carries no history, no deltas and no trend, so this page shows none and is
 * titled "Market Index" rather than "movers" (the /market/movers route path
 * is kept only so existing links do not break).
 *
 * This page explains the Market Index (what it is, its sources, what full
 * vs. limited coverage and a listing-fallback mean, and that staging prices
 * are not live) and then shows it applied to real printings - deliberately
 * never framed as a buy/sell recommendation or trading signal (see
 * docs/market_index.md "Market Index wording"). The actual calculation
 * (app.services.market_index) is unchanged by this page. */
export default function MarketIndexPage() {
  const [items, setItems] = useState<PrintUiModel[]>([]);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    fetchPrintCatalogue({ sort: "index_desc", limit: DISPLAY_LIMIT })
      .then((data) => {
        if (cancelled) return;
        setItems(data.items.map(toPrintUiModel));
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
          description="A reference price for each printing, drawn from Yuyu-Tei and SNKRDUNK - not a buy or sell recommendation."
        />

        <div className="panel mb-6 grid gap-4 p-4 text-sm text-text-secondary sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-faint">
              What it is
            </div>
            <p>
              The median of eligible prices across every contributing source - one JPY figure per
              printing, not a single source&rsquo;s price.
            </p>
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-faint">
              Contributing sources
            </div>
            <p>
              Yuyu-Tei (sell, dealer-buy) and SNKRDUNK (sold, floor listing) - see each
              printing&rsquo;s own breakdown.
            </p>
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
              Each printing shows when its most recent source observation landed - a{" "}
              <span className="text-signal-warning">stale</span> badge means over 48 hours old.
            </p>
          </div>
        </div>

        {/* Same claim as before - these staging prices are not live market
            data - without naming the backend's own scraping-mode flag, which
            is an internal implementation detail no collector can act on. */}
        <p className="mb-6 text-xs text-text-muted">
          Staging preview — prices here come from a test price source, not live market data.
        </p>

        <p className="mb-3 text-xs text-text-muted">
          Ranked by current Market Index, highest first. Printings without an index appear last.
          This is a snapshot, not price movement &mdash; no change history is published yet.
        </p>

        {status === "loading" && <CardGridSkeleton />}

        {status === "error" && (
          <ErrorState
            tone="collector"
            action={
              <button
                type="button"
                onClick={() => {
                  setStatus("loading");
                  fetchPrintCatalogue({ sort: "index_desc", limit: DISPLAY_LIMIT })
                    .then((data) => {
                      setItems(data.items.map(toPrintUiModel));
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
            The Market Index couldn&rsquo;t be loaded right now.
          </ErrorState>
        )}

        {status === "ready" && items.length === 0 && (
          <CollectorEmptyState title="No printings yet">
            The catalogue is empty right now.
          </CollectorEmptyState>
        )}

        {status === "ready" && items.length > 0 && (
          <>
            <CardGrid>
              {items.map((print) => (
                <PrintCardTile key={print.cardPrintId} print={print} />
              ))}
            </CardGrid>
            <p className="mt-6 text-xs text-text-muted">
              Looking for a specific card?{" "}
              <Link
                href="/cards"
                className="font-medium text-accent-teal hover:text-accent-teal-hover"
              >
                Browse the full catalogue →
              </Link>
            </p>
          </>
        )}
      </main>
    </div>
  );
}
