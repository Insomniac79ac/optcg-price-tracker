"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { ErrorState } from "@/components/StateBlocks";
import { CardGridSkeleton } from "@/components/ui/CardGridSkeleton";
import { PrintCardTile } from "@/components/ui/PrintCardTile";
import { HomeMovers } from "@/components/ui/HomeMovers";
import { AtlasVisualSystem, AtlasMapSurface, AtlasSectionIntro, AtlasDivider } from "@/components/ui/AtlasPrimitives";
import styles from "./Home.module.css";
import { brand } from "@/lib/brand";
import { fetchPrintCatalogue, toPrintUiModel, type PrintUiModel } from "@/lib/prints";

// One catalogue request, shared by every recently updated tile. "updated"
// means CardPrint.updated_at, not release, listing or price-observation date.
const CATALOGUE_FETCH_LIMIT = 100;
const RECENT_FINDS_LIMIT = 4;
const LINK_CLASS = "text-sm font-medium text-accent-teal hover:text-accent-teal-hover focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-teal";
type CatalogueStatus =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; items: PrintUiModel[] };

// Preserve the existing selection: priced entries first within the latest
// 100 updated records, keeping server order within each group.
function pickRecentFinds(items: PrintUiModel[]): PrintUiModel[] {
  return [...items.filter((p) => p.marketIndexJpy !== null),
    ...items.filter((p) => p.marketIndexJpy === null)].slice(0, RECENT_FINDS_LIMIT);
}

export default function HomePage() {
  const [status, setStatus] = useState<CatalogueStatus>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    fetchPrintCatalogue({ sort: "updated", limit: CATALOGUE_FETCH_LIMIT })
      .then((data) => {
        if (!cancelled) setStatus({ kind: "ready", items: data.items.map(toPrintUiModel) });
      })
      .catch(() => { if (!cancelled) setStatus({ kind: "error" }); });
    return () => { cancelled = true; };
  }, [attempt]);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <AtlasVisualSystem>
        <main className={`mx-auto max-w-6xl px-4 ${styles.home}`}>
          <div className={styles.chart}>
            <AtlasMapSurface>
              <HomeChartRoute />
              <div className={styles.opening}>
                <div className={styles.intro}>
                  <div>
                    <p className={styles.identity}>{brand.productName}</p>
                    <h1 className="mt-1 font-display text-2xl font-semibold tracking-tight text-text-primary sm:text-3xl">Find your next card.</h1>
                    <HomeCardSearch />
                  </div>
                </div>
                <HomeMovers />
              </div>
            </AtlasMapSurface>
          </div>
          <AtlasDivider />

          <section aria-labelledby="updated-printings">
            <div data-atlas-chapter>
              <AtlasSectionIntro id="updated-printings" number="02" title="Recently updated printings" description="A few recently updated catalogue entries, with priced cards shown first." />
            </div>
            {status.kind === "loading" && <CardGridSkeleton count={RECENT_FINDS_LIMIT} />}
            {status.kind === "error" && (
              <ErrorState tone="collector" action={<button type="button" className={LINK_CLASS} onClick={() => {
                setStatus({ kind: "loading" });
                setAttempt((value) => value + 1);
              }}>Try again</button>}>The catalogue couldn&rsquo;t be loaded right now.</ErrorState>
            )}
            {status.kind === "ready" && (status.items.length === 0
              ? <p className="text-sm text-text-secondary">No recently updated printings are available right now.</p>
              : <div className={styles.recentGrid}>
                  {pickRecentFinds(status.items).map((print) => <PrintCardTile key={print.cardPrintId} print={print} />)}
                </div>)}
          </section>

          <Link href="/cards" prefetch={false} className={`${LINK_CLASS} ${styles.path}`}>Browse all cards</Link>
          <AtlasDivider />
          <section aria-labelledby="home-market" className={styles.market}>
            <span className={styles.destinationMark} aria-hidden="true"><span /></span>
            <div data-atlas-chapter>
              <AtlasSectionIntro id="home-market" number="03" title="Card Pirate Index" description="See how the broader One Piece card market is moving." />
            </div>
            <Link href="/analytics" prefetch={false} className={`${LINK_CLASS} ${styles.path}`}>View Market →</Link>
          </section>
        </main>
      </AtlasVisualSystem>
    </div>
  );
}

/** Decorative chart geometry only: no coordinates, places or data series. */
function HomeChartRoute() {
  return (
    <svg className={styles.chartRoute} viewBox="0 0 1000 600" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">
      <g className={styles.chartRings}>
        <circle cx="740" cy="300" r="240" /><circle cx="740" cy="300" r="180" />
        <path d="M740 30V570 M470 300H1000" />
      </g>
      <path className={styles.chartPath} d="M35 540H280Q320 540 320 500V390Q320 350 360 350H490Q530 350 530 310V130Q530 90 570 90H930" />
      <g className={styles.chartNodes}><circle cx="35" cy="540" r="6" /><circle cx="490" cy="350" r="7" /><circle cx="930" cy="90" r="6" /></g>
    </svg>
  );
}

const MAX_SEARCH_LENGTH = 128;

/** The URL a Home search lands on. Always the public catalogue with a
 * `q` filter - never a card/print id, and never a guess at which printing
 * was meant: /cards resolves the term server-side against card code, English
 * name and Japanese name, and every result it renders is one exact printing.
 *
 * A blank or whitespace-only term produces plain /cards, never `?q=` with
 * nothing in it. */
export function buildCardsSearchHref(term: string): string {
  const q = term.trim().slice(0, MAX_SEARCH_LENGTH);
  return q ? `/cards?q=${encodeURIComponent(q)}` : "/cards";
}

/** Home's card search - an entry point into /cards, not a search of its
 * own.
 *
 * It deliberately queries nothing: no request, no suggestions, no dropdown
 * of results. Submitting navigates to /cards with the term as `q` and the
 * catalogue does what it already does. That keeps one public search
 * implementation (the print catalogue's) rather than a second one here, and
 * keeps this reachable for a signed-out visitor, which the authenticated
 * /api/search is not.
 *
 * Styled as the catalogue's own search field is (see CatalogueIntro) so the
 * two read as the same control in two places, and sized to the hero column
 * rather than spanning it - this is a way in, not the page's subject. */
function HomeCardSearch() {
  const router = useRouter();
  const [term, setTerm] = useState("");

  return (
    <form
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        router.push(buildCardsSearchHref(term));
      }}
      className="mt-4 flex w-full max-w-md gap-2"
    >
      <input
        type="search"
        name="q"
        value={term}
        onChange={(e) => setTerm(e.target.value)}
        // Examples rather than instructions: one English name, one card
        // code, one Japanese name is the whole of what /cards matches on.
        placeholder="Kaido, OP01-001, カイドウ…"
        aria-label="Search cards by name or code"
        className="min-w-0 flex-1 rounded-control border border-border-default bg-bg-surface px-3.5 py-2.5 text-sm text-text-primary placeholder:text-text-faint focus:border-accent-teal focus:outline-none focus:ring-1 focus:ring-accent-teal"
      />
      <button
        type="submit"
        className="shrink-0 rounded-control bg-accent-teal px-3.5 py-2.5 text-sm font-semibold text-bg-page transition-colors hover:bg-accent-teal-hover sm:px-5"
      >
        Search
      </button>
    </form>
  );
}
