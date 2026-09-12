"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { ErrorState } from "@/components/StateBlocks";
import { CardGridSkeleton } from "@/components/ui/CardGridSkeleton";
import { PrintCardTile } from "@/components/ui/PrintCardTile";
import { HomeMovers } from "@/components/ui/HomeMovers";
import { AtlasVisualSystem, AtlasSectionIntro, AtlasReleaseDestination } from "@/components/ui/AtlasPrimitives";
import styles from "./Home.module.css";
import { CardImageFrame } from "@/components/ui/CardImageFrame";
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

  const recent = status.kind === "ready" ? pickRecentFinds(status.items) : [];
  const preview = recent.filter((print) => print.imageUrl).slice(0, 3);
  // Codes come from the existing response, never a parallel release vocabulary.
  const releases = status.kind === "ready"
    ? [...new Set(status.items.map((print) => print.releaseCode).filter((code): code is string => Boolean(code)))].slice(0, 6)
    : [];

  return (
    <div className={styles.root}>
      <AppHeader />
      <AtlasVisualSystem>
        <main className={`mx-auto max-w-6xl px-4 ${styles.home}`}>
          <section className={styles.hero} aria-labelledby="home-title">
            <div className={styles.heroContent}>
              <div className={styles.intro}>
                <p className={styles.kicker}>Log · One Piece card printings</p>
                <h1 id="home-title">Find your <span>next card.</span></h1>
                <HomeCardSearch />
              </div>
              {preview.length > 0 && <div className={styles.fan} data-count={preview.length} aria-label="Artwork previews from recently updated printings">
                {preview.map((print) => <Link key={print.cardPrintId} href={`/prints/${print.cardPrintId}`} prefetch={false} aria-label={`Preview ${print.displayName}, ${print.cardCode}, ${print.printingType?.label ?? "printing"}`}>
                  <CardImageFrame imageUrl={print.imageUrl} alt="" cardCode={print.cardCode} rarity={print.rarity} geometry={print.imageGeometry} size="full" />
                </Link>)}
              </div>}
            </div>
            <HomeWave />
          </section>
          <HomeMovers />

          <section aria-labelledby="updated-printings">
            <div data-atlas-chapter>
              <AtlasSectionIntro id="updated-printings" number="02" title="Recent finds" description="A few recently updated catalogue entries, with priced cards shown first." />
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
                  {recent.map((print) => <PrintCardTile key={print.cardPrintId} print={print} />)}
                </div>)}
          </section>

          <section className={styles.explore} aria-labelledby="home-explore">
            <div data-atlas-chapter><AtlasSectionIntro id="home-explore" number="03" title="Explore the Atlas" /></div>
            {releases.length > 0 && <div className={styles.releaseGrid}>
              {releases.map((code) => <AtlasReleaseDestination key={code} releaseCode={code} href={`/cards?set=${encodeURIComponent(code)}`} />)}
            </div>}
            <Link href="/cards" prefetch={false} className={`${LINK_CLASS} ${styles.path}`}>Browse all cards</Link>
          </section>
          <section aria-labelledby="home-market" className={styles.market}>
            <div>
              <h2 id="home-market">Card Pirate Index</h2>
              <p>See how the broader One Piece card market is moving.</p>
            </div>
            <Link href="/analytics" prefetch={false} className={`${LINK_CLASS} ${styles.path}`}>View Market →</Link>
          </section>
        </main>
      </AtlasVisualSystem>
    </div>
  );
}

/** Repeating current marks from the reference; decorative, never chart data. */
function HomeWave() {
  return <svg className={styles.wave} viewBox="0 0 1200 24" preserveAspectRatio="none" aria-hidden="true" focusable="false">
    <path d="M0 12 Q30 2 60 12 T120 12 T180 12 T240 12 T300 12 T360 12 T420 12 T480 12 T540 12 T600 12 T660 12 T720 12 T780 12 T840 12 T900 12 T960 12 T1020 12 T1080 12 T1140 12 T1200 12" />
  </svg>;
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
 * The Home banner supplies its visual treatment; submission retains the
 * catalogue's existing public search contract. */
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
      className={styles.search}
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
        className={styles.searchSubmit}
      >
        Search
      </button>
    </form>
  );
}
