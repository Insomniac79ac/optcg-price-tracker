"use client";

import Link from "next/link";
import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { CardGrid } from "@/components/ui/CardGrid";
import { CollectorCardTile } from "@/components/ui/CollectorCardTile";
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
  const { data: session } = useSession();
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
            <h1 className="font-display text-3xl font-semibold tracking-tight text-text-primary sm:text-4xl">
              Your collection has a story.
            </h1>
            <p className="mt-3 max-w-prose text-sm text-text-secondary sm:text-base">
              Map the cards you own, keep track of the ones you&rsquo;re chasing, and understand
              where they stand through a transparent Market Index.
            </p>

            <div className="mt-6 flex flex-wrap gap-3">
              <Link href="/cards" className={PRIMARY_LINK_CLASS}>
                Explore the Atlas
              </Link>
              <Link href="/market/movers" className={SECONDARY_LINK_CLASS}>
                View Market Index
              </Link>
            </div>

            {session ? (
              <p className="mt-6 max-w-prose text-sm text-text-muted">
                Add to your collection, track your wishlist, and keep your grading progress right
                here.{" "}
                <Link href="/collection" className="text-accent-teal hover:underline">
                  My Collection →
                </Link>
              </p>
            ) : (
              <p className="mt-6 max-w-prose text-sm text-text-muted">
                Keep the cards that matter to you in one place.{" "}
                <Link href="/sign-in" className="text-accent-teal hover:underline">
                  Learn more
                </Link>
                .
              </p>
            )}
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
              <Link href="/market/movers" className="text-xs font-medium text-accent-teal hover:text-accent-teal-hover">
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
              <h2 className="text-sm font-semibold text-text-primary">Recent Finds</h2>
              <Link href="/cards" className="text-xs font-medium text-accent-teal hover:text-accent-teal-hover">
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
