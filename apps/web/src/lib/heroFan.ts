/** Which real prints the catalogue intro's decorative card fan shows today.
 *
 * The fan is atmosphere, but the cards in it are real prints from the real
 * catalogue - so this module's whole job is to pick three of them without
 * ever naming one. Nothing here contains a card_print_id, a card code, or an
 * image URL: every input comes from the `GET /prints` payload the page has
 * already loaded, and the fan never costs a request of its own.
 *
 * ## Why a daily rotation rather than "the first three"
 *
 * Taking the head of the response meant the same three cards forever, which
 * makes a catalogue of thousands look like a catalogue of three. Rotating
 * randomly in the browser would fix that and break four other things: a
 * hydration mismatch, cards swapping mid-session, cards swapping while the
 * visitor is working the filters, and screenshots/tests that can never be
 * pinned. A deterministic function of (UTC date, card_print_id) gives the
 * variety without any of that - stable all day, identical on every device,
 * and reproducible in a test by fixing the clock.
 *
 * `Math.random()` is never called, here or in render.
 *
 * ## Why the ranking ignores the order it was handed
 *
 * The rank of a print depends only on the day key and its own id, so
 * re-sorting the catalogue (card code, price, recency) cannot change which
 * three come out. That is what keeps the fan representing the wider
 * catalogue rather than the visitor's current sort - the page's filter
 * latching (see cards/page.tsx) is the other half of the same guarantee.
 */

import type { PrintUiModel } from "./prints";

/** How many prints the composition holds: one front card and two behind. */
export const HERO_FAN_SIZE = 3;

/** The display-image source that means "no cleaner image is verified for this
 * print" - the canonical artwork, SAMPLE watermark and all. Eligible for the
 * fan, but only after every verified image has had its turn. */
const FALLBACK_IMAGE_SOURCE = "bandai";

/** `YYYY-MM-DD` in UTC - the rotation's seed.
 *
 * UTC, not local time, so every visitor sees the same fan at the same moment
 * and a screenshot taken in one timezone reproduces in another. */
export function utcDayKey(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10);
}

/** FNV-1a, 32-bit. Chosen for being tiny, dependency-free and stable across
 * runtimes - the fan has to land on the same three cards in a browser, in
 * vitest and in a screenshot run. Not a security primitive and not used as
 * one. */
function hash(seed: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < seed.length; i += 1) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** A print can only appear if there is a real image to draw.
 *
 * Two exclusions, both about never dressing the panel in something that
 * isn't the card:
 * - no usable image URL means `CardImageFrame` would render its
 *   code/rarity placeholder, which is a fine tile state and a poor
 *   decoration - the fan omits the print instead.
 * - `exact_print_verified === false` means the API has looked and found the
 *   image is *not* this exact print. Where that evidence doesn't exist at all
 *   (no display image, so the value is null) there is nothing to fail, and
 *   the canonical artwork stays eligible.
 */
export function isHeroFanEligible(print: PrintUiModel): boolean {
  const url = print.imageUrl?.trim() ?? "";
  if (url === "") return false;
  return print.imageExactPrintVerified !== false;
}

/** True for an image we mirror and have verified as this exact print (today
 * that is the SNKRDUNK-sourced artwork served from our own R2 bucket) - the
 * clean, watermark-free asset the composition should prefer. */
export function prefersHeroFanImage(print: PrintUiModel): boolean {
  const source = print.imageSource?.trim().toLowerCase() ?? "";
  if (source === "" || source === FALLBACK_IMAGE_SOURCE) return false;
  return print.imageExactPrintVerified === true;
}

/** What counts as "the same artwork" for variety purposes: the canonical
 * `image_url` identifies the art itself, which two prints of one card can
 * share even when their display images differ. Falls back to the rendered
 * URL when a print carries no canonical URL. */
function artworkKey(print: PrintUiModel): string {
  return print.sourceImageUrl ?? print.imageUrl ?? String(print.cardPrintId);
}

/** Today's order for one tier: a pure function of the day key and each
 * print's own id, so the incoming array's order is irrelevant. */
function rankForDay(prints: PrintUiModel[], dayKey: string): PrintUiModel[] {
  return prints
    .map((print) => ({ print, rank: hash(`${dayKey}:${print.cardPrintId}`) }))
    .sort((a, b) => a.rank - b.rank || a.print.cardPrintId - b.print.cardPrintId)
    .map((entry) => entry.print);
}

/** The three prints the fan draws today, best first (position 1 = front).
 *
 * Preference order, applied strictly:
 * 1. verified, self-hosted display images, in today's random-looking order,
 *    skipping any print that repeats a card code or an artwork already taken;
 * 2. the same again over the canonical-artwork fallbacks;
 * 3. a relaxed pass over both tiers, in case variety could not be satisfied
 *    (a catalogue holding only two prints of one card still gets a fan).
 *
 * Returns fewer than `size` - possibly zero - when that is all the eligible
 * prints there are. It never pads the result with an ineligible print, never
 * repeats a `card_print_id`, and never invents one.
 */
export function selectHeroFanPrints(
  prints: readonly PrintUiModel[],
  dayKey: string,
  size: number = HERO_FAN_SIZE,
): PrintUiModel[] {
  if (size <= 0) return [];

  const eligible = prints.filter(isHeroFanEligible);
  const tiers = [
    rankForDay(eligible.filter(prefersHeroFanImage), dayKey),
    rankForDay(eligible.filter((print) => !prefersHeroFanImage(print)), dayKey),
  ];

  const chosen: PrintUiModel[] = [];
  const takenIds = new Set<number>();
  const takenCodes = new Set<string>();
  const takenArtwork = new Set<string>();

  for (const requireVariety of [true, false]) {
    for (const tier of tiers) {
      for (const print of tier) {
        if (chosen.length === size) return chosen;
        if (takenIds.has(print.cardPrintId)) continue;
        if (
          requireVariety &&
          (takenCodes.has(print.cardCode) || takenArtwork.has(artworkKey(print)))
        ) {
          continue;
        }
        chosen.push(print);
        takenIds.add(print.cardPrintId);
        takenCodes.add(print.cardCode);
        takenArtwork.add(artworkKey(print));
      }
    }
  }

  return chosen;
}
