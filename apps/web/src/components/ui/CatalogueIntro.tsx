"use client";

import Image from "next/image";
import { useMemo, useRef, useState, useSyncExternalStore } from "react";

import { ATLAS_MAP_TEXTURE_SRC } from "@/components/brand/AtlasBrandAssets";
import { selectHeroFanPrints, utcDayKey } from "@/lib/heroFan";
import type { PrintUiModel } from "@/lib/prints";
import { CardImageFrame } from "./CardImageFrame";

/** Below this width the intro shortens the search placeholder. Matches
 * Tailwind's `sm` breakpoint.
 *
 * It no longer gates the card fan: the fan is drawn at every width and
 * changes shape in CSS alone (see FAN_SLOTS), so artwork is part of the
 * first impression on a phone as well as a desktop. */
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

/** The discovery header for the public print catalogue.
 *
 * Deliberately a *section*, not a hero: it is short enough that real card
 * artwork is still the dominant thing on the page at 1440x900, and it sits
 * inside the catalogue's own surface rather than above it as a marketing
 * band. Its job is to show a card, say what this catalogue is, and put the
 * search box under the visitor's cursor.
 *
 * The fan is drawn at every width - two cards stacked above the copy on
 * phone/tablet, three beside it from lg. Before, it was `hidden lg:block`,
 * so the most common viewport met this product with a headline and a search
 * box and no card at all, which inverts the collector-first hierarchy the
 * whole surface is judged on.
 *
 * The only number it can show is `totalPrints`, which comes straight from
 * `GET /prints`'s `total` for the query currently in the URL - so it is the
 * real, filter-aware count, and it renders nothing at all while the response
 * is absent. No other catalogue metric exists in the API today (there is no
 * set/release facet and no source-count aggregate), and none is invented here.
 *
 * Search is presentation-only: the form hands the trimmed term to `onSearch`,
 * and the page turns that into the same `?q=` URL navigation it always did.
 * The server still matches card code, English name and Japanese name. See
 * CatalogueSearchField for the one asymmetry - emptying the box commits on
 * its own, while every other edit still waits for Enter/Search.
 */
export function CatalogueIntro({
  query,
  onSearch,
  totalPrints,
  filtered,
  heroPrints = [],
  heroPending = false,
}: {
  /** The committed search term from the URL - the single source of truth. */
  query: string;
  onSearch: (next: string) => void;
  /** `GET /prints`'s `total`, or null while loading/errored. Never a guess. */
  totalPrints: number | null;
  /** Whether any filter/search is narrowing that total right now. */
  filtered: boolean;
  /** The catalogue pool the page has *already* loaded, latched so it does not
   * track the current filter/sort (see cards/page.tsx). Used only as
   * atmosphere in the fan - this component never fetches, and it never
   * receives a hand-picked list. The same ranking feeds every width, so the
   * front card on a phone is the front card on a desktop. */
  heroPrints?: PrintUiModel[];
  /** True only while the FIRST catalogue response is still in flight, so the
   * fan's space can be held from the first frame. False once a response has
   * arrived (whatever it contained) and false on failure. */
  heroPending?: boolean;
}) {
  const narrow = useIsNarrow();
  // Read once per mount, so the fan cannot change under a visitor who is
  // still on the page at midnight UTC. Empty on the server and on the first
  // client render (there are no prints yet), so there is nothing to mismatch
  // during hydration.
  const dayKey = useMemo(() => utcDayKey(), []);
  const fanPrints = useMemo(
    () => selectHeroFanPrints(heroPrints, dayKey),
    [heroPrints, dayKey],
  );

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

      {/* Cards first in the DOM so the artwork band sits above the copy on a
          phone; `lg:order-2` puts it back on the right at desktop, where the
          existing composition is unchanged. The fan is aria-hidden, so DOM
          order costs a screen reader nothing. */}
      <div className="flex flex-col gap-2.5 px-5 py-4 sm:px-8 sm:py-6 lg:flex-row lg:items-center lg:gap-10">
        {fanPrints.length > 0 ? (
          <HeroCardFan prints={fanPrints} />
        ) : heroPending ? (
          // Space only - never a shell, a skeleton card or a repeat.
          //
          // Before this tranche the fan was `hidden lg:block`, so on a phone it
          // occupied no height in ANY load state and the hero could not shift.
          // Now that it draws at every width, rendering it only once the
          // catalogue response lands would grow the hero ~186px after first
          // paint and push the toolbar, legend and grid down with it. Holding
          // the box from the first frame is what keeps that from happening.
          //
          // Deliberately NOT rendered when the response has arrived and simply
          // had nothing drawable: that is a settled state, and reserving space
          // for a fan that will never come would leave a dead band above the
          // empty-catalogue message.
          <div aria-hidden className={FAN_BOX_CLASS} />
        ) : null}

        <div className="order-2 min-w-0 flex-1 lg:order-1">
          <p className="text-[11px] font-medium tracking-normal text-accent-teal sm:text-xs">
            Japanese One Piece singles
          </p>

          <h1
            id="catalogue-intro-heading"
            // `text-balance` so the first sentence does not leave "print."
            // orphaned on a line of its own at 390px. The <br> still forces the
            // payoff onto its own line; balancing only redistributes the words
            // before it, and is a no-op at desktop where it already fits.
            className="mt-1.5 text-balance font-display text-[26px] font-semibold leading-[1.1] tracking-tight text-text-primary sm:text-[33px]"
          >
            Same code. Different print.
            <br />
            <span className="text-parchment">Different price.</span>
          </h1>

          <p className="mt-2 text-sm text-text-secondary sm:text-[15px]">
            Base, parallel and alt art don&apos;t get lumped together.
          </p>

          <CatalogueSearchField query={query} narrow={narrow} onSearch={onSearch} />

          <div className="mt-3 flex flex-col gap-0.5 text-xs text-text-muted sm:flex-row sm:items-center sm:gap-2.5">
            {totalPrints !== null && (
              <p>
                <span className="mono font-semibold text-accent-gold">
                  {totalPrints.toLocaleString()}
                </span>{" "}
                {filtered
                  ? `matching ${totalPrints === 1 ? "printing" : "printings"}`
                  : `${totalPrints === 1 ? "printing" : "printings"} in the Atlas`}
              </p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

/** The catalogue's search box: an input, a clear (x) control, and a Search
 * button.
 *
 * The URL is still the single source of truth for `q`: whenever the committed
 * `query` prop changes - a back/forward navigation, the toolbar's "Clear
 * all", a shared link - the box is reset to it during render (React's own
 * "adjusting state when a prop changes" pattern, not an effect, which this
 * repo lints against). Deliberately not a `key` remount, which would destroy
 * the input the moment `q` cleared and drop focus on the floor right after
 * someone pressed the clear button.
 *
 * Two ways out, deliberately asymmetric:
 *
 * - Submitting (Enter, or the Search button) commits whatever is typed. This
 *   is still the only way to *start* or *change* a search: nothing fires per
 *   keystroke, so a visitor typing "OP01-013" costs one request, not eight.
 * - Emptying the box commits on its own, the moment it happens - by the x
 *   control, by backspacing the last character, or by select-all + delete,
 *   all of which are the same `onChange`. Clearing a search is a complete
 *   gesture in itself ("show me everything again"), and making someone press
 *   Search to be shown *more* results was the friction this fixes. It only
 *   fires when a committed `query` actually exists, so clearing an
 *   unsubmitted draft navigates nowhere.
 *
 * `onSearch("")` drops `q` and keeps every other filter and the sort, because
 * the page rebuilds the query string from its current filters (see
 * buildQueryString in app/cards/page.tsx) rather than resetting them - and an
 * empty `q` is omitted outright, never left behind as a bare `?q=`.
 *
 * The x is a real button with an accessible name and a tab stop; the browser's
 * own `type="search"` cancel widget is suppressed because it has neither, and
 * two clear affordances in one field is one too many.
 */
function CatalogueSearchField({
  query,
  narrow,
  onSearch,
}: {
  query: string;
  narrow: boolean;
  onSearch: (next: string) => void;
}) {
  const [value, setValue] = useState(query);
  // What the URL last said, so a *changed* committed term can be told apart
  // from a re-render carrying the same one (which must leave typing alone).
  const [committed, setCommitted] = useState(query);
  const inputRef = useRef<HTMLInputElement>(null);

  if (query !== committed) {
    setCommitted(query);
    setValue(query);
  }

  function commitIfCleared(next: string) {
    // `query`, not `value`: only a search the catalogue is actually filtered
    // by is worth a navigation to undo.
    if (query && next.trim() === "") onSearch("");
  }

  function handleChange(next: string) {
    setValue(next);
    commitIfCleared(next);
  }

  function handleClear() {
    setValue("");
    commitIfCleared("");
    inputRef.current?.focus();
  }

  return (
    // Stacks below `sm`: at 390px an inline "Search" button leaves the input
    // ~225px wide, which truncates the placeholder mid-word and makes the
    // primary interaction feel cramped. Full-width input over a full-width
    // button keeps the placeholder legible. From `sm` up there is room for
    // one row.
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSearch(value.trim());
      }}
      role="search"
      className="mt-4 flex max-w-xl flex-col gap-2 sm:flex-row"
    >
      <div className="relative min-w-0 flex-1">
        <input
          ref={inputRef}
          type="search"
          name="q"
          value={value}
          onChange={(e) => handleChange(e.target.value)}
          // Presentation only - the server matches card code, English name
          // and Japanese name either way. The long form does not fit a 390px
          // field, so narrow viewports get the short one.
          placeholder={
            narrow
              ? "Search cards by code or name…"
              : "Search by card code, English or Japanese name…"
          }
          aria-label="Search prints by card code, English name, or Japanese name"
          className="w-full min-w-0 rounded-control border border-border-default bg-bg-page/75 py-2.5 pl-3.5 pr-10 text-sm text-text-primary placeholder:text-text-faint focus:border-accent-teal focus:outline-none focus:ring-1 focus:ring-accent-teal [&::-webkit-search-cancel-button]:appearance-none"
        />
        {value !== "" && (
          <button
            type="button"
            onClick={handleClear}
            aria-label="Clear search"
            title="Clear search"
            className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-control text-text-faint transition-colors hover:text-text-secondary focus:outline-none focus-visible:ring-1 focus-visible:ring-accent-teal"
          >
            <svg
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              aria-hidden="true"
              className="h-3.5 w-3.5"
            >
              <path d="M4 4l8 8M12 4l-8 8" />
            </svg>
          </button>
        )}
      </div>
      <button
        type="submit"
        className="shrink-0 rounded-control bg-accent-teal px-3.5 py-2.5 text-sm font-semibold text-bg-page transition-colors hover:bg-accent-teal-hover sm:px-5"
      >
        Search
      </button>
    </form>
  );
}

/** Up to three real prints, fanned as atmosphere.
 *
 * Everything here is deliberately constrained:
 * - The prints are whichever three `selectHeroFanPrints` picked for today out
 *   of the catalogue the page had already fetched - never a hand-picked list,
 *   never a second request just to decorate a panel, and never sampled during
 *   render.
 * - The slots are fixed geometry, not fixed cards. Each position owns its
 *   width, offset, rotation and stacking; the artwork rotates through them
 *   daily and the composition never moves. Position 1 is the front card, 2 is
 *   behind-left, 3 is behind-right - so a print's rank decides how prominent
 *   it is, and nothing about a print decides where it sits.
 * - The arrangement is chosen by how many prints there actually are, so one
 *   or two drawable prints still get a balanced composition instead of an
 *   empty slot or a duplicated card.
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
/** The fixed slots, in DOM order so the front card paints over the two
 * behind it. Index into this by *position*, never by anything about a card. */
/** One arrangement per possible fan size, listed back-to-front so the front
 * card paints over the ones behind it.
 *
 * A catalogue with only one or two drawable prints is a real state - a narrow
 * deep link, a young catalogue, or a day when everything else fails
 * eligibility - and it gets a smaller composition rather than an empty panel
 * or a card duplicated to fill a slot. Each arrangement is balanced about the
 * container's centre line (the cards' combined span is centred on it, so the
 * one- and two-card fans read as compositions rather than as a three-card fan
 * with holes in it), and every card keeps the same widths and the same gentle
 * rotations, so nothing is squeezed, cropped or stretched to fit a gap.
 *
 * Positions still describe geometry only. Which print lands in which position
 * is `SLOT_ORDER`'s business, and no card's identity influences either. */
const FAN_SLOTS: Record<number, readonly { position: string; className: string }[]> = {
  3: [
    {
      position: "back-left",
      className:
        "left-1/2 top-4 w-[96px] -translate-x-[103px] -rotate-[11deg] opacity-85 " +
        "lg:left-0 lg:top-7 lg:w-[132px] lg:translate-x-0 lg:-rotate-[9deg]",
    },
    {
      // The third card is desktop-only: at 390px a two-card cluster is the
      // most artwork that fits without cropping or crowding the headline.
      //
      // `hidden` still DOWNLOADS this image on mobile - measured, naturalWidth
      // 600 at 390px. That is not a regression (the whole fan was
      // `hidden lg:block` before, so mobile already paid for three images and
      // drew none of them) and it is why this is one fan with a hidden slot
      // rather than two fans, which would have cost a fourth and fifth image.
      // Skipping the fetch outright needs a viewport-conditional render, and
      // that trades a fixed cost for a hydration pop in the hero - not a
      // trade this tranche is making.
      position: "back-right",
      className:
        "hidden lg:block lg:right-0 lg:top-5 lg:w-[132px] lg:rotate-[9deg] lg:opacity-85",
    },
    {
      position: "front",
      className:
        "left-1/2 top-0 w-[110px] -translate-x-[7px] -rotate-[3deg] " +
        "lg:top-0 lg:w-[158px] lg:-translate-x-1/2 lg:-rotate-[2deg]",
    },
  ],
  2: [
    {
      position: "back-left",
      className:
        "left-1/2 top-4 w-[96px] -translate-x-[103px] -rotate-[11deg] opacity-85 " +
        "lg:top-8 lg:w-[132px] lg:-translate-x-[118px] lg:-rotate-[9deg]",
    },
    {
      position: "front",
      className:
        "left-1/2 top-0 w-[110px] -translate-x-[7px] -rotate-[3deg] " +
        "lg:top-3 lg:w-[158px] lg:-translate-x-[40px] lg:-rotate-[2deg]",
    },
  ],
  1: [
    {
      position: "front",
      className:
        "left-1/2 top-0 w-[110px] -translate-x-[55px] -rotate-[3deg] " +
        "lg:top-3.5 lg:w-[158px] lg:-translate-x-1/2 lg:-rotate-[2deg]",
    },
  ],
};

/** Which selected print fills each slot: the first pick fronts the
 * composition, the next two sit behind it. Unchanged by the fan's size - a
 * two-card fan is the same front card with one supporter instead of two. */
const SLOT_ORDER: Record<string, number> = { front: 0, "back-left": 1, "back-right": 2 };

/** The fan's own box, shared by the drawn fan and by the space reserved for
 * it while the catalogue request is still in flight. One constant, because a
 * reservation that does not match the thing it reserves for is worse than no
 * reservation at all. */
const FAN_BOX_CLASS =
  "pointer-events-none relative order-1 h-[158px] w-full shrink-0 " +
  "lg:order-2 lg:h-[248px] lg:w-[336px]";

function HeroCardFan({ prints }: { prints: PrintUiModel[] }) {
  const slots = FAN_SLOTS[prints.length];
  // No prints, no panel - and never a shell, a placeholder or a repeat.
  if (!slots) return null;

  return (
    <div
      data-hero-fan=""
      aria-hidden
      // Full-width band above the copy on phone/tablet, fixed-size panel
      // beside it from lg. The height is the tallest card plus its offset
      // (110px x 88/63 = 154px, front card at top-0), reserved from the
      // first frame so the search box never jumps when the images decode.
      className={FAN_BOX_CLASS}
    >
      {slots.map((slot) => (
        <FanCard
          key={slot.position}
          print={prints[SLOT_ORDER[slot.position]]}
          position={slot.position}
          className={slot.className}
        />
      ))}
    </div>
  );
}

function FanCard({
  print,
  position,
  className,
}: {
  print: PrintUiModel;
  position: string;
  className: string;
}) {
  return (
    <div
      data-hero-fan-position={position}
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
