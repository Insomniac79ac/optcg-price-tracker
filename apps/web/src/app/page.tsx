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

const PREVIEW_COUNT = 6;

/** The public Discover page - this is a lightweight interim landing page,
 * not the final collector visual redesign (see collector-blueprint.pdf
 * Phase 8 for that). It replaces the old unconditional redirect("/dashboard")
 * (dashboard is a signed-in-only overview; forcing every visitor through it
 * was what fed the /market/movers redirect loop this task fixes - see
 * proxy.ts).
 *
 * The "Recently updated cards" strip below the hero is real catalogue data
 * (design brief Phase 10 - "use real catalogue data where available", "do
 * not fabricate popularity/trending") - just the same GET /cards/catalogue
 * the /cards page itself uses, sorted by recency. If it fails to load or
 * the catalogue is empty, the section is simply omitted rather than shown
 * as an empty panel - the primary Browse Cards/Market Index links above it
 * are the real fallback either way. */
export default function DiscoverPage() {
  const [preview, setPreview] = useState<CardCatalogueItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchCardsCatalogue({ sort: "updated", limit: PREVIEW_COUNT })
      .then((data) => {
        if (!cancelled) setPreview(data.items);
      })
      .catch(() => {
        if (!cancelled) setPreview([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 py-10">
        <div className="mx-auto max-w-2xl">
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

        {preview.length > 0 && (
          <section className="mt-10">
            <div className="mb-3 flex items-baseline justify-between">
              <h2 className="text-sm font-semibold text-text-primary">Recently updated cards</h2>
              <Link href="/cards" className="text-xs font-medium text-sky-400 hover:text-sky-300">
                View full catalogue →
              </Link>
            </div>
            <CardGrid>
              {preview.map((card) => (
                <CollectorCardTile key={card.id} card={card} />
              ))}
            </CardGrid>
          </section>
        )}
      </main>
    </div>
  );
}
