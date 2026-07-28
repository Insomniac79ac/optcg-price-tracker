import Link from "next/link";

import { AppHeader } from "@/components/AppHeader";
import { AtlasLogo } from "@/components/brand/AtlasLogo";

/** The 404 page - Next.js renders this automatically for any unmatched
 * route. Kept in the same voice as the rest of the app (plain, collector-
 * led copy, no novelty pirate terminology) rather than a generic "oops"
 * illustration. */
export default function NotFound() {
  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-lg px-4 py-16 text-center">
        <AtlasLogo className="mx-auto mb-8 justify-center" />
        <h1 className="font-display text-2xl font-semibold text-text-primary">
          This chart doesn&rsquo;t lead anywhere.
        </h1>
        <p className="mt-2 text-sm text-text-secondary">
          The page you&rsquo;re looking for doesn&rsquo;t exist, or has moved.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <Link
            href="/"
            className="rounded-control bg-accent-gold px-4 py-2 text-sm font-medium text-black/80 hover:bg-accent-gold-hover"
          >
            Back to Discover
          </Link>
          <Link
            href="/cards"
            className="rounded-control border border-border-default px-4 py-2 text-sm font-medium text-text-secondary hover:text-text-primary"
          >
            Browse Cards
          </Link>
        </div>
      </main>
    </div>
  );
}
