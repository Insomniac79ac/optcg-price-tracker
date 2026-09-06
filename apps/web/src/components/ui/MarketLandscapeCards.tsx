"use client";

/** "Cards in this view" - the collector-facing half of the market landscape.
 *
 * WHY IT IS HERE AND WHY IT IS SMALL. Everything else on /analytics is an
 * aggregate: a median, a coverage percentage, eight distribution bands. Those
 * are the point of the page, and they stay the point. But a collector reading
 * "296 priced prints" has, until this strip, had no way to see that the
 * sentence is about cards they own or want - the page could have been
 * describing any catalogue of anything. Six pieces of artwork fix that at a
 * glance, and six is deliberately not sixteen: the strip is evidence that the
 * numbers are real, not a second catalogue bolted under them.
 *
 * IT MAKES NO RANKING CLAIM, and the heading is worded to promise none.
 * "Cards in this view" says exactly what these are - some of the prints the
 * statistics above counted, in card-code order. Not the most valuable, not the
 * best performers, not movers: this tranche has no archive that could support
 * such a claim, and inventing an ordering that LOOKS like a ranking would be
 * the same dishonesty as printing a number nobody measured.
 *
 * THE ARTWORK IS NEVER CROPPED. It goes through CardImageFrame, the same
 * component the catalogue grid and the print page use, which fits the whole
 * card inside its frame (object-contain, with the API's verified geometry when
 * there is any). A cropped card is a different card to a collector - the art
 * is the thing they recognise - so this file introduces no second image
 * treatment of its own.
 *
 * THE PRICE FOLLOWS THE SELECTED BASIS, ALWAYS. See `cardBasisValue`: under a
 * source basis the number is that platform's own eligible value, and a print
 * it does not price is not on the page at all, because the server excluded it.
 * There is no fallback to a platform the collector did not select, and no
 * stored price_type is read anywhere in this file.
 */

import { CardImageFrame } from "@/components/ui/CardImageFrame";
import { formatJpy } from "@/lib/format";
import {
  cardBasisValue,
  basisPlatformLabel,
  type MarketBasis,
} from "@/lib/marketAnalytics";
import { toPrintUiModel, type PrintCatalogueItem } from "@/lib/prints";
import { instrumentLabel } from "@/lib/sourceEvidence";

export type CardsStatus = "loading" | "error" | "ready";

/** One card. Compact by construction: artwork, who it is, and the one number
 * the current basis reports. No badge row, no chart, no per-card platform
 * chip - the basis is named once above the strip, and repeating it six times
 * would be noise that competes with the statistics this page is actually
 * about. */
function MarketCard({
  item,
  basis,
}: {
  item: PrintCatalogueItem;
  basis: MarketBasis | null;
}) {
  const print = toPrintUiModel(item);
  const value = cardBasisValue(item, basis);
  // Rarity is read through the same classifier the catalogue uses, so a token
  // that names a special print (SP Card, TR) is never mislabelled "Rarity" -
  // and where the catalogue establishes no rarity at all, nothing is shown
  // rather than a filled-in guess.
  const rarity = print.rarityTerm?.label ?? print.specialPrint?.label ?? print.unknownRarityToken;

  return (
    <li className="flex w-[148px] shrink-0 flex-col sm:w-auto">
      <CardImageFrame
        imageUrl={print.imageUrl}
        alt={`${print.displayName} (${print.cardCode})`}
        cardCode={print.cardCode}
        rarity={print.rarity}
        setCode={print.releaseCode}
        size="full"
        padded
        geometry={print.imageGeometry}
      />
      <div className="flex flex-col gap-1 px-0.5 pt-2">
        {/* Truncated for the row's rhythm, but never unreadable: the full name
            is on the element, so a long one ("There's No Way You Could...") is
            recoverable on hover and is what assistive tech announces. These
            distinctive names are exactly what the strip exists to surface, so
            losing one to an ellipsis with no way back would defeat it. */}
        <span
          title={print.displayName}
          className="truncate text-[13px] font-semibold leading-snug text-text-primary"
        >
          {print.displayName}
        </span>
        <div className="mono flex flex-wrap items-center gap-x-1.5 text-[10px] leading-none text-text-muted">
          <span>{print.cardCode}</span>
          {rarity && (
            <>
              <span aria-hidden="true">·</span>
              <span>{rarity}</span>
            </>
          )}
        </div>
        {/* `!= null` rather than a truthy test: ¥0 would be a real (if
            unlikely) measurement, and null is not a small number - it is the
            absence of one. A card that reached here with no value for the
            selected basis says so, and never shows ¥0. */}
        <span className="text-[13px] font-semibold leading-none text-text-primary">
          {value != null ? formatJpy(value) : (
            <span className="text-[12px] font-normal text-text-muted">Unavailable</span>
          )}
        </span>
      </div>
    </li>
  );
}

export function MarketLandscapeCards({
  items,
  basis,
  status,
  scopeLabel,
}: {
  items: PrintCatalogueItem[];
  basis: MarketBasis | null;
  status: CardsStatus;
  /** Names the scope in the caption, so the strip cannot be read as the whole
   * catalogue when a set or rarity filter is on. */
  scopeLabel: string | null;
}) {
  const platform = basis ? basisPlatformLabel(basis) : null;
  const instrument = basis && basis.kind === "source" ? instrumentLabel(basis.reference_type) : null;
  // The basis is named ONCE, here, from the same two helpers every other
  // surface uses - so a platform this build has never heard of is named by the
  // server's own word for it, and no card below has to carry a label.
  const priceCaption = platform
    ? instrument
      ? `Prices shown are ${platform} · ${instrument}.`
      : `Prices shown are ${platform}.`
    : null;

  return (
    <section aria-labelledby="cards-in-this-view" className="mt-6">
      <h2
        id="cards-in-this-view"
        className="font-display text-[17px] font-semibold text-text-primary"
      >
        Cards in this view
      </h2>
      <p className="mt-1 text-[13px] text-text-secondary">
        {scopeLabel ? `A few of the priced prints in ${scopeLabel}.` : "A few of the priced prints counted above."}
        {priceCaption ? ` ${priceCaption}` : ""}
      </p>

      {status === "loading" && (
        // A fixed-height placeholder rather than the previous scope's cards.
        // The statistics above deliberately keep their last good answer while
        // refreshing, because a number updating in place is honest; CARDS are
        // not, because a card from the previous set would be a specific false
        // claim about this one. So the strip empties and reloads.
        <div
          aria-busy="true"
          aria-live="polite"
          className="mt-3 h-[218px] rounded-panel border border-border-muted bg-bg-elevated/40"
        />
      )}

      {status === "error" && (
        <p className="mt-3 text-[13px] text-text-muted">
          Card examples could not be loaded. The statistics above are unaffected.
        </p>
      )}

      {status === "ready" && items.length === 0 && (
        // Honest and small. No placeholder tiles, no ¥0, and nothing borrowed
        // from another platform to make the row look populated.
        <p className="mt-3 rounded-panel border border-border-muted bg-bg-elevated px-4 py-3 text-[13px] text-text-secondary">
          No priced cards match this view yet.
        </p>
      )}

      {status === "ready" && items.length > 0 && (
        // Horizontal scroll on mobile (about two cards visible, swipe for the
        // rest), a plain grid from `sm` up. The scroller is what keeps a
        // six-card row off the page's own horizontal axis at 390px - the
        // overflow belongs to this strip, never to the document.
        // ONE TRACK PER CARD, EACH CAPPED AT 168px - and a grid rather than a
        // wrapping flex row, because the two obvious alternatives each break a
        // different case. A fixed six-track grid left four empty tracks open on
        // a two-card result, which read as a page still loading. Replacing it
        // with a WRAPPING flex row fixed that but broke the common case: six
        // 168px cards do not fit the content column at 1440px, so the sixth
        // wrapped onto a row of its own - on the default unfiltered view, which
        // is the first thing anyone sees.
        //
        // A grid never wraps, so deriving the track count from the item count
        // (capped at six) ends the row exactly where the data ends, and
        // `minmax(0, 168px)` stops two cards from ballooning to half the page.
        // The inline value is inert at mobile, where the container is still the
        // horizontal scroller.
        <ul
          style={{
            gridTemplateColumns: `repeat(${Math.min(items.length, 6)}, minmax(0, 168px))`,
          }}
          className="-mx-1 mt-3 flex snap-x snap-mandatory gap-3 overflow-x-auto px-1 pb-2 sm:mx-0 sm:grid sm:overflow-visible sm:px-0"
        >
          {items.map((item) => (
            <MarketCard key={item.card_print_id} item={item} basis={basis} />
          ))}
        </ul>
      )}
    </section>
  );
}
