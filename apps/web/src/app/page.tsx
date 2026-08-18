"use client";

import Link from "next/link";
import { useSession } from "next-auth/react";
import { useCallback, useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { ErrorState } from "@/components/StateBlocks";
import { CardGrid } from "@/components/ui/CardGrid";
import { CardGridSkeleton } from "@/components/ui/CardGridSkeleton";
import { CardImageFrame } from "@/components/ui/CardImageFrame";
import { CollectorEmptyState } from "@/components/ui/CollectorEmptyState";
import { PrintCardTile } from "@/components/ui/PrintCardTile";
import { SkeletonBlock } from "@/components/ui/SkeletonBlock";
import { brand } from "@/lib/brand";
import { fetchPrintCatalogue, toPrintUiModel, type PrintUiModel } from "@/lib/prints";

const PRIMARY_LINK_CLASS =
  "rounded-control bg-accent-gold px-4 py-2 text-sm font-medium text-black/80 hover:bg-accent-gold-hover";
const SECONDARY_LINK_CLASS =
  "rounded-control border border-border-default px-4 py-2 text-sm font-medium text-text-secondary hover:text-text-primary";

// One request covers the whole page - hero art, Recent Finds, and the
// collection-invitation stack all derive from this same array. The staging
// catalogue is small enough that this is simpler and cheaper than a
// separate fetch per section.
//
// `GET /prints`, not the legacy `GET /cards/catalogue`: this page is now
// print-centric end to end, so every card shown is one exact printing with
// its own `card_print_id`, its own print-scoped Market Index and its own
// verified artwork - and every tile can link to /prints/{card_print_id}
// without anything having to guess which printing it meant. The legacy
// catalogue carried no print identity at all, and some of its rows disagree
// with the print catalogue on name, code and price.
//
// Sorted "updated" so "Recent Finds" reflects a genuine server-side signal
// (CardPrint.updated_at - see services/api/app/services/print_catalogue.py),
// never an invented popularity/trending order.
//
// 100 is the API's documented maximum for this endpoint (limit > 100 is a
// 422), so this asks for the largest page it will serve rather than a
// number that would silently fail.
const CATALOGUE_FETCH_LIMIT = 100;
const HERO_CARD_LIMIT = 3;
const RECENT_FINDS_LIMIT = 4;

type CatalogueStatus =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; items: PrintUiModel[] };

/** Real-image prints first (just reordering what the API already returned,
 * never fabricated) so the hero's limited card-art slots favor prints that
 * actually have artwork (see docs/market_index.md "Image data audit").
 * Prints without an image still render - CardImageFrame already falls back to
 * a branded placeholder - so the composition fills up to HERO_CARD_LIMIT real
 * catalogue entries instead of looking sparse. */
function pickHeroPrints(items: PrintUiModel[]): PrintUiModel[] {
  const withImage = items.filter((p) => p.imageUrl);
  const withoutImage = items.filter((p) => !p.imageUrl);
  return [...withImage, ...withoutImage].slice(0, HERO_CARD_LIMIT);
}

/** The public Discover page (collector-first redesign, Tranche 2) - built
 * entirely from a single GET /prints call, never invented
 * popularity/trending/sales-volume data. Every section degrades explicitly
 * (skeleton / empty / error), never silently to a blank gap. */
export default function DiscoverPage() {
  const { data: session } = useSession();
  const [status, setStatus] = useState<CatalogueStatus>({ kind: "loading" });

  const load = useCallback(() => {
    let cancelled = false;
    setStatus({ kind: "loading" });
    fetchPrintCatalogue({ sort: "updated", limit: CATALOGUE_FETCH_LIMIT })
      .then((data) => {
        if (!cancelled) {
          setStatus({ kind: "ready", items: data.items.map(toPrintUiModel) });
        }
      })
      .catch(() => {
        if (!cancelled) setStatus({ kind: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => load(), [load]);

  const items = status.kind === "ready" ? status.items : [];
  const isLoading = status.kind === "loading";
  const isError = status.kind === "error";
  const isEmpty = status.kind === "ready" && items.length === 0;

  const heroCards = pickHeroPrints(items);
  const recentFinds = items.slice(0, RECENT_FINDS_LIMIT);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-6xl px-4 py-10">
        {/* Hero - hierarchy #1 (card artwork) and #2 (collector message). */}
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] lg:items-start">
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-accent-teal">
              {brand.productName}
            </p>
            <h1 className="mt-2 font-display text-3xl font-semibold tracking-tight text-text-primary sm:text-4xl">
              Your collection has a story.
            </h1>
            <p className="mt-3 max-w-prose text-sm text-text-secondary sm:text-base">
              Map the cards you own, keep track of the ones you&rsquo;re chasing, and discover how
              every card fits into the wider market.
            </p>

            <div className="mt-6 flex flex-wrap gap-3">
              <Link href="/cards" className={PRIMARY_LINK_CLASS}>
                Explore the Atlas
              </Link>
              <Link href="/market/movers" className={SECONDARY_LINK_CLASS}>
                View Market Index
              </Link>
            </div>
          </div>

          <HeroArt loading={isLoading} cards={heroCards} />
        </div>

        {/* Hierarchy #3 - card identity and discovery. */}
        <RecentFindsSection
          loading={isLoading}
          error={isError}
          empty={isEmpty}
          cards={recentFinds}
          onRetry={load}
        />

        {/* Hierarchy #4 - collection invitation. */}
        <CollectionInvitation authenticated={Boolean(session)} stackCards={heroCards.slice(0, 2)} />

        {/* Hierarchy #5 - Market Index context, kept brief. */}
        <MarketIndexPreview />
      </main>
    </div>
  );
}

/** Fanned card-art composition - a small stack, not a grid, so it reads as
 * "opening a collection" rather than a catalogue browser. Reserves the same
 * footprint while loading (same aspect-ratio skeleton frames) so real
 * artwork never shifts the layout on arrival. Purely decorative - the
 * heading/copy beside it already carries the same message in text, so the
 * whole composition is aria-hidden rather than exposing unlabeled card
 * fragments to assistive tech. Desktop shows up to 3 cards fanned; tablet
 * shows 2; mobile shows a single centered card. */
function HeroArt({ loading, cards }: { loading: boolean; cards: PrintUiModel[] }) {
  if (loading) {
    return (
      <div aria-hidden="true" data-testid="hero-art-loading" className="flex justify-center gap-3 lg:justify-end">
        <SkeletonBlock className="aspect-[63/88] w-24 rounded-panel sm:w-28" />
        <SkeletonBlock className="hidden aspect-[63/88] w-24 rounded-panel sm:block sm:w-28" />
        <SkeletonBlock className="hidden aspect-[63/88] w-24 rounded-panel lg:block lg:w-28" />
      </div>
    );
  }

  if (cards.length === 0) return null;

  const fanTransform = ["-rotate-3", "-translate-y-2", "rotate-3"];
  const visibility = ["", "hidden sm:block", "hidden lg:block"];

  return (
    <div aria-hidden="true" data-testid="hero-art" className="flex justify-center gap-3 lg:justify-end">
      {cards.map((print, i) => (
        <div
          key={print.cardPrintId}
          className={`w-24 shrink-0 sm:w-28 ${visibility[i]} ${fanTransform[i]}`}
        >
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
        </div>
      ))}
    </div>
  );
}

function RecentFindsSection({
  loading,
  error,
  empty,
  cards,
  onRetry,
}: {
  loading: boolean;
  error: boolean;
  empty: boolean;
  cards: PrintUiModel[];
  onRetry: () => void;
}) {
  return (
    <section className="mt-12">
      <div className="mb-3 flex items-baseline justify-between">
        <div>
          <h2 className="text-sm font-semibold text-text-primary">Recent Finds</h2>
          <p className="text-xs text-text-muted">
            Newly added or recently updated printings from across the Atlas.
          </p>
        </div>
        {!loading && !error && !empty && (
          <Link
            href="/cards"
            className="text-xs font-medium text-accent-teal hover:text-accent-teal-hover"
          >
            View full catalogue →
          </Link>
        )}
      </div>

      {loading && <CardGridSkeleton count={RECENT_FINDS_LIMIT} />}

      {!loading && error && (
        <ErrorState
          tone="collector"
          action={
            <button type="button" onClick={onRetry} className={SECONDARY_LINK_CLASS}>
              Try again
            </button>
          }
        >
          The catalogue couldn&rsquo;t be loaded right now.
        </ErrorState>
      )}

      {!loading && !error && empty && (
        <CollectorEmptyState
          title="The Atlas is waiting to be mapped."
          action={
            <Link
              href="/cards"
              className="text-xs font-medium text-accent-teal hover:text-accent-teal-hover"
            >
              Browse Cards →
            </Link>
          }
        >
          Catalogue data hasn&rsquo;t been loaded for this view yet.
        </CollectorEmptyState>
      )}

      {!loading && !error && !empty && (
        <CardGrid>
          {cards.map((print) => (
            <PrintCardTile key={print.cardPrintId} print={print} />
          ))}
        </CardGrid>
      )}
    </section>
  );
}

function CollectionInvitation({
  authenticated,
  stackCards,
}: {
  authenticated: boolean;
  stackCards: PrintUiModel[];
}) {
  return (
    <section className="panel-elevated mt-14 rounded-panel-lg p-6 sm:p-8">
      <div className="grid gap-6 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
        <div>
          {authenticated ? (
            <>
              <h2 className="font-display text-xl font-semibold text-text-primary">
                Your collection, in one place.
              </h2>
              <p className="mt-2 max-w-prose text-sm text-text-secondary">
                Add to your collection, track your wishlist, and keep your grading progress
                together.
              </p>
              <Link href="/collection" className={`${PRIMARY_LINK_CLASS} mt-4 inline-flex`}>
                My Collection →
              </Link>
            </>
          ) : (
            <>
              <h2 className="font-display text-xl font-semibold text-text-primary">
                Chart your collection.
              </h2>
              <p className="mt-2 max-w-prose text-sm text-text-secondary">
                Keep the cards that matter to you together, remember what you own, and keep the
                ones you&rsquo;re still chasing in sight.
              </p>
              <Link href="/sign-in" className={`${PRIMARY_LINK_CLASS} mt-4 inline-flex`}>
                Learn about collections
              </Link>
            </>
          )}
        </div>

        {stackCards.length > 0 && (
          <div aria-hidden="true" className="hidden -space-x-8 sm:flex sm:justify-end">
            {stackCards.map((print, i) => (
              <div
                key={print.cardPrintId}
                className={`w-20 shrink-0 ${i === 1 ? "translate-y-2 rotate-3" : "-rotate-3"}`}
              >
                <CardImageFrame
                  imageUrl={print.imageUrl}
                  alt=""
                  cardCode={print.cardCode}
                  rarity={print.rarity}
                  setCode={print.releaseCode}
                  size="full"
                  padded
                  geometry={print.imageGeometry}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function MarketIndexPreview() {
  return (
    <section className="mt-10 border-t border-border-muted pt-8">
      <h2 className="font-display text-lg font-semibold text-text-primary">
        A clearer view of the market.
      </h2>
      <p className="mt-2 max-w-prose text-sm text-text-secondary">
        The Market Index combines eligible references from Yuyu-Tei and SNKRDUNK so you can
        understand the context around a card without reducing collecting to a single price.
      </p>
      <Link
        href="/market/movers"
        className="mt-3 inline-flex text-sm font-medium text-accent-teal hover:text-accent-teal-hover"
      >
        Explore the Market Index →
      </Link>
    </section>
  );
}
