"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { CardGrid } from "@/components/ui/CardGrid";
import { CollectorCardTile } from "@/components/ui/CollectorCardTile";
import { PageHeader } from "@/components/ui/PageHeader";
import { type CardCatalogueItem, fetchCardsCatalogue } from "@/lib/api";

const PRIMARY_LINK_CLASS =
  "rounded-control bg-accent-gold px-4 py-2 text-sm font-medium text-black/80 hover:bg-accent-gold-hover";
const SECONDARY_LINK_CLASS =
  "rounded-control border border-border-default px-4 py-2 text-sm font-medium text-text-secondary hover:text-text-primary";

// One request covers every section below (the whole staging catalogue is
// small enough that "updated" order plus client-side filtering is simpler
// and cheaper than three separate fetches) - see the sections' own comments
// for how each is derived from the same `catalogue` array.
const CATALOGUE_FETCH_LIMIT = 100;
const SECTION_CARD_LIMIT = 6;
const ARTWORK_PREVIEW_LIMIT = 3;

/** The public Discover page (collector-first redesign audit, Phase 5) - the
 * strongest demonstration of the collector product a visitor sees before
 * ever browsing the full catalogue. Replaces the earlier interim version
 * (a hero plus one "recently updated" strip) with the full structure the
 * audit calls for: a real-artwork preview, a "full Market Index coverage"
 * section, "recently updated", and clear links onward - built from a single
 * GET /cards/catalogue call, never invented popularity/trending/sales-volume
 * data. Every section is omitted (not shown empty) if the catalogue can't
 * supply it - the primary Browse Cards/Market Index links in the intro are
 * the real fallback either way. */
export default function DiscoverPage() {
  const [catalogue, setCatalogue] = useState<CardCatalogueItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchCardsCatalogue({ sort: "updated", limit: CATALOGUE_FETCH_LIMIT })
      .then((data) => {
        if (!cancelled) setCatalogue(data.items);
      })
      .catch(() => {
        if (!cancelled) setCatalogue([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Real artwork only - most staging cards still show the branded
  // placeholder (see docs/market_index.md "Image data audit"), so this is
  // deliberately whatever subset actually has an image, not a fixed count.
  const withArtwork = catalogue.filter((c) => c.image_url).slice(0, ARTWORK_PREVIEW_LIMIT);
  const fullCoverage = catalogue
    .filter((c) => c.market_index.coverage_status === "full")
    .slice(0, SECTION_CARD_LIMIT);
  const recentlyUpdated = catalogue.slice(0, SECTION_CARD_LIMIT);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-6xl px-4 py-10">
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] lg:items-start">
          <div>
            <PageHeader
              title="Track your One Piece TCG collection"
              description="Browse the card catalogue and follow the Market Index across Yuyu-Tei and SNKRDUNK - then keep your own collection, wishlist and grading progress alongside it."
            />

            <div className="flex flex-wrap gap-3">
              <Link href="/cards" className={PRIMARY_LINK_CLASS}>
                Browse Cards
              </Link>
              <Link href="/market/movers" className={SECONDARY_LINK_CLASS}>
                View Market Index
              </Link>
            </div>

            <p className="mt-6 max-w-prose text-sm text-text-muted">
              Collection tracking, wishlist and grading are available once you have a collector
              account.{" "}
              <Link href="/sign-in" className="text-sky-400 hover:underline">
                Learn more
              </Link>
              .
            </p>
          </div>

          {/* Visual card preview using real artwork where available (Phase 5,
              item 2) - a small showcase, not a grid, so 1-2 real cards still
              read as a deliberate feature rather than a sparse row. */}
          {withArtwork.length > 0 && (
            <div className="flex justify-center gap-3 lg:justify-end">
              {withArtwork.map((card) => (
                <div key={card.id} className="w-28 sm:w-32">
                  <CollectorCardTile card={card} />
                </div>
              ))}
            </div>
          )}
        </div>

        {fullCoverage.length > 0 && (
          <section className="mt-12">
            <div className="mb-3 flex items-baseline justify-between">
              <div>
                <h2 className="text-sm font-semibold text-text-primary">
                  Full Market Index coverage
                </h2>
                <p className="text-xs text-text-muted">
                  Cards with a Yuyu-Tei and SNKRDUNK price both eligible right now.
                </p>
              </div>
              <Link href="/market/movers" className="text-xs font-medium text-sky-400 hover:text-sky-300">
                About the Market Index →
              </Link>
            </div>
            <CardGrid>
              {fullCoverage.map((card) => (
                <CollectorCardTile key={card.id} card={card} />
              ))}
            </CardGrid>
          </section>
        )}

        {recentlyUpdated.length > 0 && (
          <section className="mt-12">
            <div className="mb-3 flex items-baseline justify-between">
              <h2 className="text-sm font-semibold text-text-primary">Recently updated cards</h2>
              <Link href="/cards" className="text-xs font-medium text-sky-400 hover:text-sky-300">
                View full catalogue →
              </Link>
            </div>
            <CardGrid>
              {recentlyUpdated.map((card) => (
                <CollectorCardTile key={card.id} card={card} />
              ))}
            </CardGrid>
          </section>
        )}
      </main>
    </div>
  );
}
