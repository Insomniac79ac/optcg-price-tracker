"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { ErrorState } from "@/components/StateBlocks";
import { MarketLandscapeCards, type CardsStatus } from "@/components/ui/MarketLandscapeCards";
import type { PrintCatalogueItem } from "@/lib/prints";
import { MarketLandscapeFilters } from "@/components/ui/MarketLandscapeFilters";
import {
  MarketCoverageComposition,
  MarketLandscapeStats,
  MarketMovementUnavailable,
  MarketPriceDistribution,
} from "@/components/ui/MarketLandscapeSections";
import {
  MARKET_INDEX_BASIS,
  fetchMarketBases,
  fetchMarketCards,
  fetchMarketFilters,
  fetchMarketOverview,
  isOfferedBasis,
  isOfferedOption,
  overviewBasisLabel,
  type MarketBasis,
  type MarketFilterOption,
  type MarketOverview,
} from "@/lib/marketAnalytics";

/** /analytics - the current market landscape.
 *
 * WHAT THIS PAGE ANSWERS, and the boundary it keeps: how much of the catalogue
 * Atlas can price right now, what that price landscape looks like, and how
 * both change when read through the Market Index versus one platform, or
 * narrowed to a set or a rarity. It is explicitly NOT a movers dashboard -
 * there are no gainers, no losers, no rankings, no percentage changes and no
 * sentiment, because the archive behind this product cannot yet answer a
 * movement question honestly. The one section that names movement says exactly
 * that instead of drawing an empty chart.
 *
 * STATE LIVES IN THE URL, the same convention /cards keeps, so a view a
 * collector arrives at is a view they can share and return to. Every value
 * read out of the query string is validated against the SERVER's own option
 * lists before it is used - a `?basis=` naming a retired platform, or a
 * `?set=` naming a set that no longer has active prints, falls back to the
 * default rather than requesting a slice nothing can answer.
 */
export default function MarketLandscapePage() {
  return (
    <Suspense fallback={<MarketLandscapeFallback />}>
      <MarketLandscapePageInner />
    </Suspense>
  );
}

function PageFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 py-5">
        <header className="mb-4">
          <p className="mono text-[10px] font-medium uppercase tracking-[0.22em] text-accent-teal">
            Atlas market analytics
          </p>
          <h1 className="mt-2 font-display text-[26px] font-semibold leading-[1.15] tracking-tight text-text-primary sm:text-[30px]">
            Current market landscape
          </h1>
          {children}
        </header>
      </main>
    </div>
  );
}

function MarketLandscapeFallback() {
  return (
    <PageFrame>
      <p className="mt-1.5 text-sm text-text-secondary">
        Pricing coverage and distribution across the current One Piece Card Game catalogue.
      </p>
      <div className="mt-4">
        <MarketLandscapeSkeleton />
      </div>
    </PageFrame>
  );
}

/** The controls' vocabularies, fetched once. Both lists are the server's, and
 * the page renders no control until it has them - an empty selector is honest
 * about knowing nothing, a guessed one is not. */
interface Vocabulary {
  bases: MarketBasis[];
  sets: MarketFilterOption[];
  rarities: MarketFilterOption[];
}

function MarketLandscapePageInner() {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [vocabulary, setVocabulary] = useState<Vocabulary | null>(null);
  const [vocabularyFailed, setVocabularyFailed] = useState(false);
  /** The most recent SETTLED overview request, tagged with the selection it
   * answers.
   *
   * Tagged rather than accompanied by a status flag, because the flag would
   * have to be set to "loading" synchronously inside the effect - a cascading
   * render, and what `react-hooks/set-state-in-effect` exists to catch.
   * Comparing the tag against the current selection during RENDER derives the
   * same answer with no extra state: a result for a selection the visitor has
   * already moved on from is, by definition, still loading. */
  const [settled, setSettled] = useState<{
    key: string;
    overview: MarketOverview | null;
    failed: boolean;
  } | null>(null);
  /** The "Cards in this view" strip, tagged with the selection it answers -
   * the same staleness discipline as `settled`, and for a stricter reason.
   *
   * The statistics deliberately keep the PREVIOUS scope's numbers on screen
   * while a new scope loads, because a figure updating in place beats
   * collapsing a thousand pixels of page. Cards get no such grace: OP01-001's
   * artwork under an EB-02 heading is not a stale number, it is a specific
   * false statement about which cards are in this set. So a result whose tag
   * no longer matches the selection is treated as no result at all, and the
   * strip shows its placeholder until the right one lands. A slow response
   * for an abandoned filter can therefore never overwrite a newer one. */
  const [cards, setCards] = useState<{
    key: string;
    items: PrintCatalogueItem[];
    failed: boolean;
  } | null>(null);

  // The two vocabulary endpoints, once per mount. They describe the catalogue,
  // not the current view, so nothing about changing a filter can invalidate
  // them.
  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchMarketBases(), fetchMarketFilters()])
      .then(([basesResponse, filtersResponse]) => {
        if (cancelled) return;
        setVocabulary({
          bases: basesResponse.bases,
          sets: filtersResponse.sets,
          rarities: filtersResponse.rarities,
        });
      })
      .catch(() => {
        if (!cancelled) setVocabularyFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Selection is derived from the URL and the server's option lists together,
  // so it is never a value the server would reject. Until the vocabulary
  // arrives there is nothing to validate against, and the request waits.
  const rawBasis = searchParams.get("basis") ?? "";
  const rawSet = searchParams.get("set") ?? "";
  const rawRarity = searchParams.get("rarity") ?? "";

  const selectedBasis =
    vocabulary && isOfferedBasis(vocabulary.bases, rawBasis) ? rawBasis : MARKET_INDEX_BASIS;
  const selectedSet = vocabulary && isOfferedOption(vocabulary.sets, rawSet) ? rawSet : "";
  const selectedRarity =
    vocabulary && isOfferedOption(vocabulary.rarities, rawRarity) ? rawRarity : "";

  const ready = vocabulary !== null;

  // One string identifying the whole selection, so the effect has a single
  // dependency and the settled result has something to be compared against.
  const requestKey = `${selectedBasis}|${selectedSet}|${selectedRarity}`;

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    fetchMarketOverview({
      priceBasis: selectedBasis,
      set: selectedSet || undefined,
      rarity: selectedRarity || undefined,
    })
      .then((result) => {
        if (!cancelled) setSettled({ key: requestKey, overview: result, failed: false });
      })
      .catch(() => {
        if (!cancelled) setSettled({ key: requestKey, overview: null, failed: true });
      });
    return () => {
      cancelled = true;
    };
  }, [ready, requestKey, selectedBasis, selectedSet, selectedRarity]);

  // The card strip, on the same selection and the same cancellation
  // discipline. A separate request rather than a field on the overview: the
  // two answer different questions, and a failure to fetch six pieces of
  // artwork must not take the statistics down with it.
  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    fetchMarketCards({
      priceBasis: selectedBasis,
      set: selectedSet || undefined,
      rarity: selectedRarity || undefined,
    })
      .then((result) => {
        if (!cancelled) setCards({ key: requestKey, items: result.items, failed: false });
      })
      .catch(() => {
        if (!cancelled) setCards({ key: requestKey, items: [], failed: true });
      });
    return () => {
      cancelled = true;
    };
  }, [ready, requestKey, selectedBasis, selectedSet, selectedRarity]);

  const current = settled && settled.key === requestKey ? settled : null;
  /** The PREVIOUS selection's result, still on screen while the new one loads.
   *
   * Without this the page swapped its whole body for a small loading box on
   * every basis/set/rarity change, so each click collapsed ~1000px of content
   * and then snapped it back - a visible layout shift on an interaction a
   * collector makes repeatedly. Keeping the last good answer rendered (marked
   * `aria-busy`, dimmed slightly) means the page never changes height while it
   * refreshes: the numbers update in place. */
  const previous = settled && settled.key !== requestKey && !settled.failed ? settled : null;
  const showing = current ?? previous;
  const refreshing = current === null && previous !== null;
  const overviewStatus: "loading" | "error" | "ready" = current?.failed
    ? "error"
    : showing?.overview
      ? "ready"
      : "loading";
  const overview = showing?.overview ?? null;

  /** The strip's own status. Unlike the statistics there is no "previous"
   * fallback: a result tagged with a superseded selection is not shown. */
  const currentCards = cards && cards.key === requestKey ? cards : null;
  const cardsStatus: CardsStatus = currentCards
    ? currentCards.failed
      ? "error"
      : "ready"
    : "loading";
  const cardItems = currentCards && !currentCards.failed ? currentCards.items : [];
  /** Names the scope in the strip's caption, from the SERVER's own tokens, so
   * it can never claim a scope the request did not ask for. */
  const scopeLabel =
    [selectedSet, selectedRarity].filter(Boolean).join(" · ") || null;
  const selectedBasisRow =
    vocabulary?.bases.find((row) => row.key === selectedBasis) ?? null;

  /** Commits a selection to the URL.
   *
   * Native History API rather than `router.push`, for the reason /cards
   * documents at length: a prefetched static route answers a push from a URL
   * that already carries search params with a replaceState back to where you
   * are, so the address bar never changes and `useSearchParams()` never fires.
   */
  function commit(next: { basis?: string; set?: string; rarity?: string }) {
    const params = new URLSearchParams();
    const basis = next.basis ?? selectedBasis;
    const set = next.set ?? selectedSet;
    const rarity = next.rarity ?? selectedRarity;
    if (basis && basis !== MARKET_INDEX_BASIS) params.set("basis", basis);
    if (set) params.set("set", set);
    if (rarity) params.set("rarity", rarity);
    const qs = params.toString();
    window.history.pushState(null, "", `${pathname}${qs ? `?${qs}` : ""}`);
    // pushState alone does not notify the App Router, so the derived selection
    // above would not change. Dispatching popstate is what makes
    // useSearchParams re-read - the same mechanism /cards relies on.
    window.dispatchEvent(new PopStateEvent("popstate"));
  }

  const description = overview
    ? `Read through ${overviewBasisLabel(overview)}. Pricing coverage and distribution across the current One Piece Card Game catalogue.`
    : "Pricing coverage and distribution across the current One Piece Card Game catalogue.";

  return (
    <PageFrame>
      <p className="mt-1.5 max-w-prose text-sm leading-relaxed text-text-secondary">
        {description}
      </p>

      <div className="mt-4 space-y-3">
        {vocabularyFailed ? (
          <ErrorState tone="collector">
            The market landscape could not be loaded. Please try again shortly.
          </ErrorState>
        ) : !vocabulary ? (
          <MarketLandscapeSkeleton />
        ) : (
          <>
            <MarketLandscapeFilters
              bases={vocabulary.bases}
              sets={vocabulary.sets}
              rarities={vocabulary.rarities}
              selectedBasis={selectedBasis}
              selectedSet={selectedSet}
              selectedRarity={selectedRarity}
              onBasisChange={(basis) => commit({ basis })}
              onSetChange={(set) => commit({ set })}
              onRarityChange={(rarity) => commit({ rarity })}
              onClear={() => commit({ set: "", rarity: "" })}
            />

            {overviewStatus === "error" ? (
              <ErrorState tone="collector">
                This view of the market could not be loaded. Please try again shortly.
              </ErrorState>
            ) : !overview ? (
              <MarketLandscapeSkeleton />
            ) : (
              // `aria-busy` rather than a swap: assistive tech is told the
              // region is updating, while sighted readers keep the numbers
              // they were looking at instead of watching the page collapse.
              <div
                aria-busy={refreshing}
                className={
                  refreshing ? "opacity-60 transition-opacity motion-reduce:transition-none" : ""
                }
              >
                <MarketLandscapeBody
                  overview={overview}
                  cardItems={cardItems}
                  cardsStatus={cardsStatus}
                  basis={selectedBasisRow}
                  scopeLabel={scopeLabel}
                />
              </div>
            )}
          </>
        )}
      </div>
    </PageFrame>
  );
}

/** A first-paint placeholder the SHAPE of the real page.
 *
 * The generic LoadingState is a small centred box; used here it made the page
 * ~1000px shorter while loading and taller the instant data arrived. This
 * mirrors the real layout - four stat tiles, then a chart-sized block - so the
 * page occupies roughly its final height from the first frame. It carries the
 * loading caption for assistive tech rather than showing it as a heading. */
function MarketLandscapeSkeleton() {
  return (
    <div aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading market landscape…</span>
      <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="panel px-3.5 py-3">
            <div className="h-2.5 w-20 rounded bg-bg-elevated" />
            <div className="mt-2.5 h-6 w-24 rounded bg-bg-elevated" />
            <div className="mt-2 h-2 w-28 rounded bg-bg-elevated" />
          </div>
        ))}
      </div>
      <div className="panel mt-3 px-4 py-3.5">
        <div className="h-3 w-36 rounded bg-bg-elevated" />
        <div className="mt-4 space-y-2.5">
          {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
            <div key={i} className="h-3.5 rounded bg-bg-elevated" />
          ))}
        </div>
      </div>
    </div>
  );
}

/** Everything below the controls, for one loaded response.
 *
 * Two states come before the statistics, and both are the server's own
 * judgement rather than this component's:
 *
 *   an empty scope        the set/rarity combination selects no active
 *                         prints. There is no coverage percentage for it
 *                         (0/0 is not 0%) and no distribution, so the page
 *                         says the scope is empty instead of rendering four
 *                         zeros.
 *   an unavailable basis  the server reports `available: false` - an
 *                         unconfigured platform, or one with nothing priced
 *                         in this scope. Its counts are truthfully zero and
 *                         are still shown, because "this platform prices
 *                         nothing here" is an answer worth reading.
 */
function MarketLandscapeBody({
  overview,
  cardItems,
  cardsStatus,
  basis,
  scopeLabel,
}: {
  overview: MarketOverview;
  cardItems: PrintCatalogueItem[];
  cardsStatus: CardsStatus;
  basis: MarketBasis | null;
  scopeLabel: string | null;
}) {
  if (overview.scope.active_prints === 0) {
    return (
      <div className="panel px-4 py-6 text-center">
        <p className="text-sm text-text-secondary">No active prints match this scope.</p>
        <p className="mt-1.5 text-[13px] text-text-muted">
          Coverage and price statistics need a catalogue to describe. Try clearing a filter.
        </p>
      </div>
    );
  }

  return (
    <>
      {!overview.available && <BasisUnavailableNote overview={overview} />}
      <MarketLandscapeStats overview={overview} />
      <MarketLandscapeCards
        items={cardItems}
        basis={basis}
        status={cardsStatus}
        scopeLabel={scopeLabel}
      />
      <CatalogueLink rarity={overview.scope.rarity} />
      <MarketPriceDistribution overview={overview} />
      <MarketCoverageComposition overview={overview} />
      <MarketMovementUnavailable />
    </>
  );
}

/** The way out, into the card-first surface.
 *
 * Without it this page is a terminal dead end: a collector reads that 296
 * prints are priced and has nowhere to go and look at one. The link is
 * deliberately modest about what it promises, because /cards cannot reproduce
 * this page's scope.
 *
 * RARITY IS CARRIED, SET IS NOT, and that asymmetry is the API's, not a
 * shortcut: `GET /prints` accepts `rarity` - filtered through the same
 * `effective_rarity_sql` + alias expansion this page's rarity values come from,
 * so the token means the same thing on both sides - and accepts no set or
 * release parameter at all. Passing `?set=` would put a parameter in the URL
 * that /cards silently ignores, and the collector would land on the whole
 * catalogue believing they were looking at one set. So the label never claims
 * "these cards": it offers the catalogue, and narrows it only by the one
 * dimension that genuinely survives the trip. */
function CatalogueLink({ rarity }: { rarity: string | null }) {
  const href = rarity ? `/cards?rarity=${encodeURIComponent(rarity)}` : "/cards";
  return (
    <p className="text-[13px]">
      <Link
        href={href}
        className="rounded-control text-accent-teal underline-offset-2 transition-colors hover:text-accent-teal-hover hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60"
      >
        {rarity ? `Browse ${rarity} cards in the catalogue` : "Browse the card catalogue"} →
      </Link>
    </p>
  );
}

/** Why a selected basis has nothing to say, in the server's own two reasons.
 *
 * A quiet note, not a warning: a platform that does not price a set is
 * ordinary, and the coral/red vocabulary belongs to the admin surface. An
 * unrecognised reason renders the generic sentence rather than a guess. */
function BasisUnavailableNote({ overview }: { overview: MarketOverview }) {
  const detail =
    overview.unavailable_reason === "source_not_configured"
      ? "Atlas does not currently price with this source."
      : "This source has no usable prices in the current scope.";
  return (
    <div className="rounded-panel border border-border-muted bg-bg-elevated px-4 py-3">
      <p className="text-[13px] text-text-secondary">{detail}</p>
      <p className="mt-1 text-[12px] text-text-muted">
        The counts below are genuinely zero for this view — not missing.
      </p>
    </div>
  );
}
