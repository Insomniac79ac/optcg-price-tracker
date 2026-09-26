"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { ErrorState } from "@/components/StateBlocks";
import { CardPirateIndexHero, type IndexStatus } from "@/components/ui/CardPirateIndexHero";
import { IndexCompositionPanel } from "@/components/ui/IndexCompositionPanel";
import { IndexMoversPanel } from "@/components/ui/IndexMoversPanel";
import { MarketCardsSection } from "@/components/ui/MarketCardsSection";
import { MarketBreadthPanel } from "@/components/ui/MarketBreadthPanel";
import { MarketLandscapeFilters } from "@/components/ui/MarketLandscapeFilters";
import {
  MarketCoverageComposition,
  MarketLandscapeStats,
  MarketPriceDistribution,
} from "@/components/ui/MarketLandscapeSections";
import {
  fetchIndexComposition,
  fetchIndexDefault,
  fetchIndexMovers,
  fetchIndexSeries,
  pressedWindow,
  type IndexComposition,
  type IndexMovers,
  type MoverOrder,
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

import { fetchReleases, releaseLabel, type ReleaseCatalogueItem } from "@/lib/releases";
import { releaseLabelEnglish } from "@/lib/releaseNames";

/** Broad-market Index above a separately scoped current-price snapshot.
 * Release membership and mover cohorts are always the server's decisions.
 * Snapshot scope lives in the URL; mover mode and Index window are independent.
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
        <p className="text-xs font-medium text-accent-teal">
          One Piece card market
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
  releases: ReleaseCatalogueItem[] | null;
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
  /** The composition, fetched ONCE per mount and never per window.
   *
   * It describes the newest published point, which is the same point whether
   * the chart above is showing two weeks or everything - so this deliberately
   * lives outside the window state entirely rather than being memoised against
   * it. There is no window in `fetchIndexComposition`'s signature to pass.
   *
   * Its failure is panel-local: `status: "error"` renders a quiet unavailable
   * line inside the composition panel, while the breadth panel beside it keeps
   * rendering from the index series and the rest of the page is untouched. */
  const [composition, setComposition] = useState<{
    data: IndexComposition | null;
    status: "loading" | "ready" | "error";
  }>({ data: null, status: "loading" });
  /** What moved the index, fetched per mode and never per scope or window.
   *
   * Exactly the composition's discipline, and for exactly the same reason: it
   * describes the newest published point, which does not change when a reader
   * presses 2W or 1Y. `fetchIndexMovers` takes no window argument to pass one,
   * so the timeframe control cannot reach this request even by accident.
   *
   * Its failure is section-local: `status: "error"` renders one quiet
   * unavailable line inside the movers panel while the hero, the chart, the
   * composition and the breadth panel - all built from other responses - keep
   * rendering untouched. */
  const [moverOrder, setMoverOrder] = useState<MoverOrder>("move");
  const [movers, setMovers] = useState<{
    order: MoverOrder;
    data: IndexMovers | null;
    status: "loading" | "ready" | "error";
  }>({ data: null, status: "loading", order: "move" });
  // Server vocabularies, once per mount. They describe the catalogue,
  // not the current view, so nothing about changing a filter can invalidate
  // them.
  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchMarketBases(), fetchMarketFilters(), fetchReleases().catch(() => null)])
      .then(([basesResponse, filtersResponse, releasesResponse]) => {
        if (cancelled) return;
        setVocabulary({
          bases: basesResponse.bases,
          releases: releasesResponse?.items ?? null,
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
  const rawRelease = searchParams.get("release_product_id");
  const rawRarity = searchParams.get("rarity") ?? "";

  const selectedBasis =
    vocabulary && isOfferedBasis(vocabulary.bases, rawBasis) ? rawBasis : MARKET_INDEX_BASIS;
  const legacyMatches = vocabulary?.releases?.filter((r) => r.official_code === rawSet) ?? [];
  const legacyReleaseId = rawRelease === null && legacyMatches.length === 1
    ? legacyMatches[0].release_product_id : undefined;
  // Explicit IDs stay authoritative even if a product is absent from the picker.
  const selectedReleaseId = rawRelease !== null
    ? (/^[1-9]\d*$/.test(rawRelease) && Number.isSafeInteger(Number(rawRelease)) ? Number(rawRelease) : undefined)
    : legacyReleaseId;
  // Old bookmarks that cannot be uniquely canonicalized retain the legacy
  // server selector. New navigation writes only authoritative product IDs.
  const legacySet = rawRelease === null && selectedReleaseId === undefined
    && vocabulary && isOfferedOption(vocabulary.sets, rawSet) ? rawSet : "";
  const selectedRelease = vocabulary?.releases?.find((r) => r.release_product_id === selectedReleaseId);

  useEffect(() => {
    if (legacyReleaseId === undefined) return;
    const params = new URLSearchParams(window.location.search);
    if (params.has("release_product_id")) return;
    params.delete("set");
    params.set("release_product_id", String(legacyReleaseId));
    window.history.replaceState(null, "", `${pathname}?${params}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, [legacyReleaseId, pathname]);
  const selectedRarity =
    vocabulary && isOfferedOption(vocabulary.rarities, rawRarity) ? rawRarity : "";

  const ready = vocabulary !== null;

  // One string identifying the whole selection, so the effect has a single
  // dependency and the settled result has something to be compared against.
  const requestKey = `${selectedBasis}|${selectedReleaseId ?? legacySet}|${selectedRarity}`;

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    fetchMarketOverview({
      priceBasis: selectedBasis,
      release_product_id: selectedReleaseId,
      ...(legacySet ? { set: legacySet } : {}),
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
  }, [ready, requestKey, selectedBasis, selectedReleaseId, selectedRarity, legacySet]);

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
  // The composition, once per mount. No window parameter, so a timeframe
  // change cannot reach it.
  useEffect(() => {
    let cancelled = false;
    fetchIndexComposition()
      .then((data) => {
        if (cancelled) return;
        // VALIDATED AT THE TRUST BOUNDARY. A response without a usable
        // `rarity` array is not a composition, and treating it as one puts an
        // undefined through the panel's own length check - a render-time throw
        // that React escalates into a blank Analytics page. A malformed
        // payload is a failure, and failures here are panel-local by design.
        if (!data || !Array.isArray(data.rarity)) {
          setComposition({ data: null, status: "error" });
          return;
        }
        setComposition({ data, status: "ready" });
      })
      .catch(() => {
        if (!cancelled) setComposition({ data: null, status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Each mode requests its own server cohort. Scope and window cannot reach it.
  useEffect(() => {
    let cancelled = false;
    fetchIndexMovers(moverOrder)
      .then((data) => {
        if (cancelled) return;
        // VALIDATED AT THE TRUST BOUNDARY, the same way the composition is. A
        // response without a usable `movers` array is not a movers payload,
        // and mapping over an undefined is a render-time throw that React
        // escalates into a blank Analytics page - so a malformed body is a
        // failure here, and failures here are section-local by design.
        if (!data || !Array.isArray(data.movers)) {
          setMovers({ data: null, status: "error", order: moverOrder });
          return;
        }
        setMovers({ data, status: "ready", order: moverOrder });
      })
      .catch(() => {
        if (!cancelled) setMovers({ data: null, status: "error", order: moverOrder });
      });
    return () => {
      cancelled = true;
    };
  }, [moverOrder]);

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
  function commit(next: { basis?: string; release?: string; rarity?: string }) {
    const params = new URLSearchParams();
    const basis = next.basis ?? selectedBasis;
    const release = next.release ?? (selectedReleaseId === undefined ? "" : String(selectedReleaseId));
    const rarity = next.rarity ?? selectedRarity;
    if (basis && basis !== MARKET_INDEX_BASIS) params.set("basis", basis);
    if (release) params.set("release_product_id", release);
    if (rarity) params.set("rarity", rarity);
    const qs = params.toString();
    window.history.pushState(null, "", `${pathname}${qs ? `?${qs}` : ""}`);
    // pushState alone does not notify the App Router, so the derived selection
    // above would not change. Dispatching popstate is what makes
    // useSearchParams re-read - the same mechanism /cards relies on.
    window.dispatchEvent(new PopStateEvent("popstate"));
  }

  // The newest point of whatever series is on screen. Breadth is a property
  // of the latest published day, and every window's response ends on that
  // same day, so this is stable across timeframe changes rather than being
  // another thing the window control moves.
  const points = indexShowing?.series?.points ?? [];
  const newestIndexPoint = points.length > 0 ? points[points.length - 1] : null;

  const description = overview
    ? `Using ${overviewBasisLabel(overview)}. Which One Piece prints have prices, and how those prices are spread.`
    : "Which One Piece prints have prices, and how those prices are spread.";

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

      {/* The cards behind the latest move follow the chart. */}
      <IndexMoversPanel
        movers={movers.order === moverOrder ? movers.data : null}
        status={movers.order === moverOrder ? movers.status : "loading"}
        order={moverOrder}
        onOrderChange={setMoverOrder}
      />

      <section className="mt-8" aria-labelledby="market-landscape-heading">
        <h2
          id="market-landscape-heading"
          className="font-display text-[20px] font-semibold leading-[1.15] tracking-tight text-text-primary sm:text-[23px]"
        >
          {selectedRelease ? releaseLabel(selectedRelease) : selectedReleaseId ? "Selected release" : legacySet ? releaseLabelEnglish(legacySet) : "Market snapshot"}
        </h2>
        <p className="mt-1.5 max-w-prose text-sm leading-relaxed text-text-secondary">
          {selectedReleaseId !== undefined || legacySet ? "Current prices in this release. " : ""}{description}
        </p>
      </section>

      <div className="mt-4 space-y-3">
        {vocabularyFailed ? (
          <ErrorState tone="collector">
            Catalogue prices could not be loaded. Please try again shortly.
          </ErrorState>
        ) : !vocabulary ? (
          <MarketLandscapeSkeleton />
        ) : (
          <>
            <MarketLandscapeFilters
              bases={vocabulary.bases}
              releases={vocabulary.releases}
              rarities={vocabulary.rarities}
              selectedBasis={selectedBasis}
              selectedRelease={selectedReleaseId === undefined ? (legacySet ? `legacy:${legacySet}` : "") : String(selectedReleaseId)}
              selectedRarity={selectedRarity}
              onBasisChange={(basis) => commit({ basis })}
              onReleaseChange={(release) => commit({ release })}
              onRarityChange={(rarity) => commit({ rarity })}
              onClear={() => commit({ release: "", rarity: "" })}
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
      <MarketCardsSection
        selection={{ priceBasis: selectedBasis, release_product_id: selectedReleaseId, rarity: selectedRarity || undefined, ...(legacySet ? { set: legacySet } : {}) }}
        basis={vocabulary?.bases.find((basis) => basis.key === selectedBasis) ?? null}
        ready={ready}
        unavailable={vocabularyFailed}
      />

      <section className="mt-10 border-t border-border-muted pt-5" aria-labelledby="market-structure-heading" data-testid="market-structure">
        <h2 id="market-structure-heading" className="font-display text-lg font-semibold text-text-secondary">Market structure</h2>
        <div className="mt-5" data-testid="current-price-structure">
          <h3 className="text-sm font-medium text-text-secondary">Current-price structure</h3>
          <p className="mt-1 text-xs leading-relaxed text-text-muted">Price distribution and source coverage follow the Release, Rarity and Price basis above.</p>
          {overviewStatus === "error" || vocabularyFailed ? (
            <p className="mt-4 text-sm text-text-muted">Current-price structure is unavailable for this view.</p>
          ) : !overview ? (
            <p className="mt-4 text-sm text-text-muted" aria-busy="true">Loading current-price structure…</p>
          ) : overview.scope.active_prints > 0 ? (
            <div aria-busy={refreshing} className={`mt-3 space-y-4 [&>section]:rounded-none [&>section]:border-0 [&>section]:bg-transparent [&>section]:px-0 ${refreshing ? "opacity-60" : ""}`}>
              <MarketPriceDistribution overview={overview} />
              <MarketCoverageComposition overview={overview} />
            </div>
          ) : <p className="mt-4 text-sm text-text-muted">There are no active prints to describe in this scope.</p>}
        </div>
        <section className="mt-6 border-t border-border-muted pt-5" aria-labelledby="broad-index-structure-heading">
          <h3 id="broad-index-structure-heading" className="text-sm font-medium text-text-secondary">Broad Index structure</h3>
          <div className="mt-3 grid grid-cols-1 gap-5 lg:grid-cols-2 [&>section]:rounded-none [&>section]:border-0 [&>section]:bg-transparent [&>section]:px-0" data-testid="index-analytics-row">
            <IndexCompositionPanel composition={composition.data} status={composition.status} />
            <MarketBreadthPanel point={newestIndexPoint} />
          </div>
        </section>
      </section>
    </PageFrame>
  );
}

/** A first-paint placeholder the SHAPE of the real page.
 *
 * The generic LoadingState is a small centred box; used here it made the page
 * ~1000px shorter while loading and taller the instant data arrived. This
 * mirrors the real layout - coverage and supporting prices - so the
 * page occupies roughly its final height from the first frame. It carries the
 * loading caption for assistive tech rather than showing it as a heading. */
function MarketLandscapeSkeleton() {
  return (
    <div aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading catalogue prices…</span>
      <div className="panel p-4 sm:p-5">
        <div className="h-8 w-3/4 rounded bg-bg-elevated" />
        <div className="mt-2 h-4 w-28 rounded bg-bg-elevated" />
        <div className="mt-5 grid gap-4 border-t border-border-muted pt-4 sm:grid-cols-2">
          {[0, 1].map((i) => (
            <div key={i}>
              <div className="h-3 w-28 rounded bg-bg-elevated" />
              <div className="mt-2 h-6 w-32 rounded bg-bg-elevated" />
            </div>
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
          Try clearing a filter to see more of the catalogue.
        </p>
      </div>
    );
  }

  return (
    <>
      {!overview.available && <BasisUnavailableNote overview={overview} />}
      <MarketLandscapeStats overview={overview} />
    </>
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
