import Link from "next/link";

import { AppHeader } from "@/components/AppHeader";
import { PageHeader } from "@/components/ui/PageHeader";

const PRIMARY_LINK_CLASS =
  "rounded-control bg-accent-gold px-4 py-2 text-sm font-medium text-black/80 hover:bg-accent-gold-hover";
const SECONDARY_LINK_CLASS =
  "rounded-control border border-border-default px-4 py-2 text-sm font-medium text-text-secondary hover:text-text-primary";

/** The public Discover page - this is a lightweight interim landing page,
 * not the final collector visual redesign (see collector-blueprint.pdf
 * Phase 8 for that). It replaces the old unconditional redirect("/dashboard")
 * (dashboard is a signed-in-only overview; forcing every visitor through it
 * was what fed the /market/movers redirect loop this task fixes - see
 * proxy.ts). */
export default function DiscoverPage() {
  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-2xl px-4 py-10">
        <PageHeader
          title="Track your One Piece TCG collection"
          description="Browse the card catalogue and follow the Market Index across Yuyu-Tei and SNKRDUNK - then keep your own collection, wishlist and grading progress alongside it."
        />

        <div className="flex flex-wrap gap-3">
          <Link href="/search" className={PRIMARY_LINK_CLASS}>
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
      </main>
    </div>
  );
}
