"use client";

import Image from "next/image";
import { useSyncExternalStore } from "react";

import { ATLAS_MAP_TEXTURE_SRC } from "@/components/brand/AtlasBrandAssets";
import type { PrintUiModel } from "@/lib/prints";
import { CardImageFrame } from "./CardImageFrame";

/** Below this width the intro drops the card fan and shortens the search
 * placeholder. Matches Tailwind's `sm` breakpoint. */
const NARROW_QUERY = "(max-width: 639px)";

function subscribeToNarrow(onChange: () => void): () => void {
  const media = window.matchMedia(NARROW_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

/** `useSyncExternalStore` rather than `useState` + an effect: the repo lints
 * against `setState` inside an effect, and this is exactly the case the hook
 * exists for. The server snapshot is `false`, so SSR and the first client
 * render agree on the desktop placeholder and a narrow viewport corrects it
 * on hydration. */
function useIsNarrow(): boolean {
  return useSyncExternalStore(
    subscribeToNarrow,
    () => window.matchMedia(NARROW_QUERY).matches,
    () => false,
  );
}

/** How many prints the hero fan shows, and the minimum needed to draw it. A
 * two-card fan reads as a rendering accident rather than a composition, so
 * below three the intro simply keeps its negative space. */
const FAN_SIZE = 3;

/** The discovery header for the public print catalogue.
 *
 * Deliberately a *section*, not a hero: it is short enough that real card
 * artwork is still the dominant thing on the page at 1440x900, and it sits
 * inside the catalogue's own surface rather than above it as a marketing
 * band. Its job is to say what market this indexes and put the search box
 * under the visitor's cursor.
 *
 * The only number it can show is `totalPrints`, which comes straight from
 * `GET /prints`'s `total` for the query currently in the URL - so it is the
 * real, filter-aware count, and it renders nothing at all while the response
 * is absent. No other catalogue metric exists in the API today (there is no
 * set/release facet and no source-count aggregate), and none is invented here.
 *
 * Search is presentation-only: the form hands the trimmed term to `onSearch`,
 * and the page turns that into the same `?q=` URL navigation it always did.
 * The server still matches card code, English name and Japanese name.
 */
export function CatalogueIntro({
  query,
  onSearch,
  totalPrints,
  filtered,
  prints = [],
}: {
  /** The committed search term from the URL - the single source of truth. */
  query: string;
  onSearch: (next: string) => void;
  /** `GET /prints`'s `total`, or null while loading/errored. Never a guess. */
  totalPrints: number | null;
  /** Whether any filter/search is narrowing that total right now. */
  filtered: boolean;
  /** The prints the page has *already* loaded for this query. Used only as
   * atmosphere in the desktop fan - this component never fetches. */
  prints?: PrintUiModel[];
}) {
  const narrow = useIsNarrow();
  const fanPrints = prints.slice(0, FAN_SIZE);

  function submitSearch(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const entered = new FormData(e.currentTarget).get("q");
    onSearch(typeof entered === "string" ? entered.trim() : "");
  }

  return (
    <section
      aria-labelledby="catalogue-intro-heading"
      className="relative isolate overflow-hidden rounded-panel-lg border border-border-default bg-bg-surface"
    >
      {/* Atmosphere layer.
          - Anchored top-left because the supplied texture concentrates its
            cartography around the edges and leaves the middle near-black: on
            a wide desktop panel that keeps the two upper corner roses in
            frame, and on a narrow mobile panel it keeps the left-hand column
            of detail rather than cropping to empty centre.
          - Blended with `screen` so only the drawn lines survive: the asset's
            own near-black navy field contributes nothing, which stops the
            panel turning into a blue rectangle sitting off-palette from the
            warm charcoal surfaces around it.
          - The wash on top is what guarantees text contrast, heaviest behind
            the headline and lightest out at the right where there is no text.
            Readability never depends on the texture being dark enough. */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <Image
          src={ATLAS_MAP_TEXTURE_SRC}
          data-brand-asset=""
          alt=""
          fill
          priority
          sizes="(min-width: 1024px) 1200px, 100vw"
          className="object-cover object-left-top mix-blend-screen"
        />
        <div className="absolute inset-0 bg-[linear-gradient(105deg,rgba(23,23,23,0.9)_0%,rgba(23,23,23,0.78)_38%,rgba(23,23,23,0.28)_100%)]" />
      </div>

      <div className="flex items-center gap-10 px-5 py-5 sm:px-8 sm:py-7">
        <div className="min-w-0 flex-1">
          <p className="mono text-[10px] font-medium uppercase tracking-[0.22em] text-accent-teal sm:text-[11px]">
            Japanese One Piece card market
          </p>

          <h1
            id="catalogue-intro-heading"
            className="mt-2.5 font-display text-[26px] font-semibold leading-[1.1] tracking-tight text-text-primary sm:text-[33px]"
          >
            Navigate the market.
            <br />
            <span className="text-parchment">Collect with confidence.</span>
          </h1>

          <p className="mt-2 text-sm text-text-secondary sm:text-[15px]">Two markets. One index.</p>

          {/* Stacks below `sm`: at 390px an inline "Search" button leaves the
              input ~225px wide, which truncates the placeholder mid-word and
              makes the primary interaction feel cramped. Full-width input
              over a full-width button keeps the placeholder legible. From
              `sm` up there is room for one row. */}
          <form
            onSubmit={submitSearch}
            role="search"
            className="mt-4 flex max-w-xl flex-col gap-2 sm:flex-row"
          >
            {/* Uncontrolled, keyed on the committed term: the URL is the single
                source of truth for `q`, and re-keying resets the box whenever a
                back/forward navigation or "Clear all" changes it - no state to
                keep in sync, so no sync effect. */}
            <input
              key={query}
              type="search"
              name="q"
              defaultValue={query}
              // Presentation only - the server matches card code, English name
              // and Japanese name either way. The long form does not fit a
              // 390px field, so narrow viewports get the short one.
              placeholder={
                narrow
                  ? "Search cards by code or name…"
                  : "Search by card code, English or Japanese name…"
              }
              aria-label="Search prints by card code, English name, or Japanese name"
              className="min-w-0 flex-1 rounded-control border border-border-default bg-bg-page/75 px-3.5 py-2.5 text-sm text-text-primary placeholder:text-text-faint focus:border-accent-teal focus:outline-none focus:ring-1 focus:ring-accent-teal"
            />
            <button
              type="submit"
              className="shrink-0 rounded-control bg-accent-teal px-3.5 py-2.5 text-sm font-semibold text-bg-page transition-colors hover:bg-accent-teal-hover sm:px-5"
            >
              Search
            </button>
          </form>

          <div className="mt-3 flex flex-col gap-0.5 text-xs text-text-muted sm:flex-row sm:items-center sm:gap-2.5">
            {totalPrints !== null && (
              <p>
                <span className="mono font-semibold text-accent-gold">
                  {totalPrints.toLocaleString()}
                </span>{" "}
                {filtered
                  ? `matching ${totalPrints === 1 ? "print" : "prints"}`
                  : `tracked ${totalPrints === 1 ? "print" : "prints"}`}
              </p>
            )}
            {totalPrints !== null && <span aria-hidden className="hidden sm:inline">·</span>}
            <p>Every printing is its own card here — base and parallel are collected separately.</p>
          </div>
        </div>

        {fanPrints.length === FAN_SIZE && <HeroCardFan prints={fanPrints} />}
      </div>
    </section>
  );
}

/** Three real prints from the page's own results, fanned as atmosphere.
 *
 * Everything here is deliberately constrained:
 * - The prints are the first three of whatever `GET /prints` returned for the
 *   current query - deterministic, never sampled or shuffled, and never a
 *   second request just to decorate a panel.
 * - Presentation goes through `CardImageFrame`, the same component the
 *   catalogue grid uses, so the fan inherits the bounded-geometry rules
 *   rather than re-implementing them. No card pixel is ever cropped: the
 *   frame either contains the whole asset or, with verified geometry, fits
 *   the verified *card box* and clips only the transparent canvas outside it.
 *   `padded` keeps the frame's own corner radius off the artwork's corners.
 * - Fixed width and height on the container, with the cards absolutely
 *   placed inside it, so the rotated cards can never push the panel wider
 *   and cause horizontal overflow.
 * - `lg`+ only. At `md` the panel is not wide enough to hold both the
 *   headline column and a fan without squeezing one of them, and on a phone
 *   the brief calls for omitting it outright rather than shrinking it.
 *
 * Decorative, so the whole block is `aria-hidden` and non-interactive: these
 * are not links, and the real, labelled, clickable versions of these same
 * cards are in the grid directly below. No names or prices here.
 */
function HeroCardFan({ prints }: { prints: PrintUiModel[] }) {
  const [backLeft, backRight, front] = prints;

  return (
    <div
      data-hero-fan=""
      aria-hidden
      className="pointer-events-none relative hidden h-[248px] w-[336px] shrink-0 lg:block"
    >
      <FanCard print={backLeft} className="left-0 top-7 w-[132px] -rotate-[9deg] opacity-85" />
      <FanCard print={backRight} className="right-0 top-5 w-[132px] rotate-[9deg] opacity-85" />
      <FanCard
        print={front}
        className="left-1/2 top-0 w-[158px] -translate-x-1/2 -rotate-[2deg]"
      />
    </div>
  );
}

function FanCard({ print, className }: { print: PrintUiModel; className: string }) {
  return (
    <div
      className={`absolute drop-shadow-[0_10px_22px_rgba(0,0,0,0.5)] ${className}`}
    >
      <CardImageFrame
        imageUrl={print.imageUrl}
        alt=""
        cardCode={print.cardCode}
        rarity={print.rarity}
        setCode={print.releaseCode}
        size="full"
        padded
        geometry={print.imageGeometry}
      />
    </div>
  );
}
