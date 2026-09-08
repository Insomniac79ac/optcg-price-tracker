"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { ErrorState } from "@/components/StateBlocks";
import { CardPirateIndexHero, type IndexStatus } from "@/components/ui/CardPirateIndexHero";
import { MarketLandscapeFilters } from "@/components/ui/MarketLandscapeFilters";
import {
  MarketCoverageComposition,
  MarketLandscapeStats,
  MarketPriceDistribution,
} from "@/components/ui/MarketLandscapeSections";
import {
  fetchIndexDefault,
  fetchIndexSeries,
  pressedWindow,
  type IndexSeries,
} from "@/lib/cardPirateIndex";
import {
  MARKET_INDEX_BASIS,
  fetchMarketBases,
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
 * WHAT THIS PAGE ANSWERS. Where the One Piece market stands today and how it
 * has moved - the Card Pirate Index, which leads the page and owns its
 * hierarchy - and then how much of the catalogue Atlas can price to say so,
 * and how that coverage changes when read through the Market Index versus one
 * platform, or narrowed to a set or a rarity.
 *
 * It is still NOT a movers dashboard: no gainers, no losers, no rankings, no
 * per-card sentiment. The index is an aggregate over the whole priced
 * catalogue, and the one movement figure on the page is the server's own
 * published change across a window the reader selected. Until this tranche the
 * page carried a section whose entire content was that the archive could not
 * answer a movement question; the index answers it, so that section is gone
 * rather than left standing beside a chart that contradicts it.
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

/** THE INDEX OWNS THE TOP OF THIS PAGE, and the frame is what makes that true
 * rather than merely stated.
 *
 * Before this tranche the frame opened with a display-weight "Current market
 * landscape" H1 and the coverage tiles beneath it. The index hero now sits
 * immediately under the eyebrow and carries the page's H1, and "Current
 * market landscape" has become an H2 introducing the coverage section further
 * down - which is what it always described. Leaving the old H1 in place would
 * have put a heading above the chart claiming the page was about something
 * else. */
function PageFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 py-5">
        <p className="mono text-[10px] font-medium uppercase tracking-[0.22em] text-accent-teal">
          Atlas market analytics
        </p>
        {children}
      </main>
    </div>
  );
}

function MarketLandscapeFallback() {
  return (
    <PageFrame>
      <div className="mt-2">
        <CardPirateIndexHero
          series={null}
          status="loading"
          refreshing={false}
          window=""
          onWindowChange={() => {}}
        />
      </div>
      <div className="mt-6">
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
  /** The index series, tagged with the WINDOW it answers.
   *
   * Same staleness discipline as `settled`, and it matters more here: the
   * windows all return within a few hundred milliseconds of each other, so a
   * reader pressing 2W then ALL can easily have the 2W response land second.
   * Comparing the tag against the current window during render means a result
   * for a window the reader has moved on from is, by definition, still
   * loading - and can never overwrite the newer selection's chart. */
  const [index, setIndex] = useState<{
    window: string;
    series: IndexSeries | null;
    failed: boolean;
  } | null>(null);
  /** Null until the server has published its `default_window`.
   *
   * The page does not have an opinion about which window to open on and never
   * had a right to one: section 13.1's ladder is the server's, and before
   * TASK INDEX 2A-B this client re-implemented it by probing `3m` and reading
   * `covers_requested_window` off the answer. That probe is gone. */
  const [indexWindow, setIndexWindow] = useState<string | null>(null);
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

  // The index, once per mount, requested with NO window at all.
  //
  // ONE REQUEST, and the server decides which window it answers. There is no
  // bootstrap token and no ladder on this side: TASK INDEX 2A-C moved the
  // `?window=` fallback and the published `default_window` into one rule, so
  // "give me the default" is expressed by naming nothing. The response's
  // `requested_window` says which window came back, and that is the button
  // that lights up.
  //
  // The page therefore does not know - and must not learn - which window is
  // the product default. The day three months of history exists this same
  // request returns `3m`, with no frontend change and no second round trip.
  useEffect(() => {
    let cancelled = false;
    fetchIndexDefault()
      .then((series) => {
        if (cancelled) return;
        const opened = pressedWindow(series);
        setIndexWindow(opened);
        setIndex({ window: opened, series, failed: false });
      })
      .catch(() => {
        if (cancelled) return;
        // No window to name, because none was chosen and none was returned.
        // The hero renders its error state; the control stays empty rather
        // than claiming a selection nothing was requested for.
        setIndex({ window: "", series: null, failed: true });
        setIndexWindow("");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Every later window change is its own server request for that token. No
  // window is ever answered by slicing a longer one already in hand: the
  // change, the high and the low are the server's for the window it was asked
  // about, and re-deriving them from a wider series is how a client starts
  // publishing a second index.
  useEffect(() => {
    if (indexWindow === null || indexWindow === "") return;
    // The first response already answers its own window; re-fetching it here
    // would double every first paint.
    if (index && index.window === indexWindow) return;
    let cancelled = false;
    fetchIndexSeries(indexWindow)
      .then((series) => {
        if (!cancelled) setIndex({ window: indexWindow, series, failed: false });
      })
      .catch(() => {
        if (!cancelled) setIndex({ window: indexWindow, series: null, failed: true });
      });
    return () => {
      cancelled = true;
    };
    // `index` is deliberately not a dependency: it is written by this effect,
    // and reading it here is a guard against the duplicate first fetch, not a
    // trigger for another one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [indexWindow]);

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

  /** The index's own status, on the same tagged-result discipline.
   *
   * `indexCurrent` is the result for the window on screen; `indexPrevious` is
   * the last good one for a window the reader has moved on from, kept
   * rendered (dimmed, aria-busy) so pressing a window does not collapse the
   * tallest object on the page and snap it back. A FAILED previous result is
   * not kept - a chart that is both stale and wrong is worse than a skeleton. */
  const indexCurrent = index && index.window === indexWindow ? index : null;
  const indexPrevious =
    index && index.window !== indexWindow && !index.failed ? index : null;
  const indexShowing = indexCurrent ?? indexPrevious;
  const indexStatus: IndexStatus = indexCurrent?.failed
    ? "error"
    : indexShowing?.series
      ? "ready"
      : "loading";
  const indexRefreshing = indexCurrent === null && indexPrevious !== null;

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
      <div className="mt-2">
        <CardPirateIndexHero
          series={indexShowing?.series ?? null}
          status={indexStatus}
          refreshing={indexRefreshing}
          window={indexWindow ?? ""}
          onWindowChange={setIndexWindow}
        />
      </div>

      <section className="mt-8" aria-labelledby="market-landscape-heading">
        <h2
          id="market-landscape-heading"
          className="font-display text-[20px] font-semibold leading-[1.15] tracking-tight text-text-primary sm:text-[23px]"
        >
          Current market landscape
        </h2>
        <p className="mt-1.5 max-w-prose text-sm leading-relaxed text-text-secondary">
          {description}
        </p>
      </section>

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
                <MarketLandscapeBody overview={overview} />
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
function MarketLandscapeBody({ overview }: { overview: MarketOverview }) {
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
      <CatalogueLink rarity={overview.scope.rarity} />
      <MarketPriceDistribution overview={overview} />
      <MarketCoverageComposition overview={overview} />
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
