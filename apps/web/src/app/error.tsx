"use client";

import { useEffect } from "react";

import { AtlasLogo } from "@/components/brand/AtlasLogo";

/** Root error boundary - Next.js requires this to be a Client Component.
 * Deliberately does not render <AppHeader /> (which itself does client-side
 * data fetching via useSession) - if the error originated in shared shell
 * state, re-rendering that same shell here could throw again. Kept minimal
 * and self-contained on purpose. */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="max-w-md text-center">
        <AtlasLogo className="mx-auto mb-8 justify-center" />
        <h1 className="font-display text-2xl font-semibold text-text-primary">
          Something went wrong charting that.
        </h1>
        <p className="mt-2 text-sm text-text-secondary">
          This didn&rsquo;t affect your collection or wishlist - try again, or head back to
          Discover.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <button
            type="button"
            onClick={reset}
            className="rounded-control bg-accent-gold px-4 py-2 text-sm font-medium text-black/80 hover:bg-accent-gold-hover"
          >
            Try again
          </button>
          <a
            href="/"
            className="rounded-control border border-border-default px-4 py-2 text-sm font-medium text-text-secondary hover:text-text-primary"
          >
            Back to Discover
          </a>
        </div>
      </div>
    </div>
  );
}
