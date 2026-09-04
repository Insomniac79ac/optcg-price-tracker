import Link from "next/link";

import { RarityTermBadge, SpecialPrintBadge, UnknownRarityBadge } from "@/components/RarityBadge";
import { formatJpy } from "@/lib/format";
import { type PrintUiModel, sourceDisplayName } from "@/lib/prints";
import {
  isUnavailableSourceValue,
  SOURCE_PRICE_UNAVAILABLE_LABEL,
  unavailableSourceValues,
} from "@/lib/sourceAvailability";
import {
  displayedSourceValues,
  isReferenceOnly,
  REFERENCE_ONLY_LABEL,
} from "@/lib/sourceContribution";
import { sourceEvidenceLabel } from "@/lib/sourceEvidence";
import { CardImageFrame } from "./CardImageFrame";
import { MarketIndexValue } from "./MarketIndexValue";

/** One collectible print in the public catalogue grid.
 *
 * The single collector-facing card tile. It replaced the legacy
 * card_id-keyed CollectorCardTile once Discover and the Market Index page
 * moved onto `GET /prints` too, so there is no longer a second, canonical
 * tile for it to drift from.
 *
 * Keyed by `card_print_id` end to end - its link, its React key, and its
 * price all belong to exactly one print, so a base and a parallel that bridge
 * through the same legacy card render as two independent tiles with two
 * independent prices.
 *
 * Hierarchy is artwork, then name, then code/set, then rarity + special
 * print + printing, then Market Index, then the sources behind it - the
 * collector-UI skill's ordering. Everything the API returns but a collector
 * doesn't need mid-browse (card type, language, confidence, verification
 * status) is deliberately left off the tile.
 *
 * The artwork is the only thing here with any real colour: the tile itself is
 * a charcoal surface with a hairline border and no gradient, glow or frame
 * ornament, so a wall of these reads as a wall of *cards*. The one accent is
 * gold on the Market Index; teal appears only on hover/focus.
 *
 * Every value shown comes from this print's own catalogue payload. Nothing
 * here fetches, and nothing is derived from a sibling print.
 */
export function PrintCardTile({
  print,
  showArtOrdinal = false,
}: {
  print: PrintUiModel;
  /** Last-resort disambiguator. The grid sets it only for prints whose
   * collector-facing label would otherwise be identical to another tile's -
   * see `needsArtOrdinal` in CardGrid. Never on by default: "Art 3" on every
   * alt art would be noise, and the printing badge alone separates most
   * tiles. */
  showArtOrdinal?: boolean;
}) {
  // The printing type is derived from Bandai's own asset address, never from
  // artwork, rarity or product - and a base printing gets nothing, which is
  // what makes an "Alt Art" beside it read as the different one.
  const printingType = print.printingType;
  const artOrdinal = showArtOrdinal ? print.artOrdinal : null;
  // Rarity, special print and printing are three different facts, so the
  // accessible name says all three in the order the badges below read - never
  // the raw token, and never one standing in for another.
  const accessibleName = [
    print.displayName,
    print.cardCode,
    print.rarityTerm?.label,
    print.specialPrint?.label,
    print.unknownRarityToken,
    printingType?.label,
    artOrdinal,
    print.releaseCode ? `found in ${print.releaseCode}` : null,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <Link
      href={`/prints/${print.cardPrintId}`}
      aria-label={accessibleName}
      className="group flex flex-col rounded-panel border border-border-muted bg-bg-elevated p-2 transition duration-150 hover:-translate-y-0.5 hover:border-accent-teal/45 hover:bg-bg-elevated/80 focus:outline-none focus-visible:border-accent-teal focus-visible:ring-2 focus-visible:ring-accent-teal/60 motion-reduce:transition-none motion-reduce:hover:translate-y-0"
    >
      {/* Untouched: bounded geometry, the natural-size guard, exact-print
          image selection and the no-crop contract all live in
          CardImageFrame and are passed through exactly as before. */}
      <CardImageFrame
        imageUrl={print.imageUrl}
        alt={`${print.displayName} (${print.cardCode})`}
        cardCode={print.cardCode}
        // The RAW token: the placeholder has room for one chip only, and
        // RarityBadge classifies it there rather than being handed a label.
        rarity={print.rarity}
        setCode={print.releaseCode}
        size="full"
        padded
        geometry={print.imageGeometry}
      />

      {/* Three identity rows, then the money. Every tile has all three rows
          whether or not it has a treatment, so tiles in a row stay the same
          height and their prices line up along the bottom.

          The rows are separated by a hair more than they were: at gap-1 with
          tight leading the name, the code and the rarity read as one grey
          clump under the artwork. The extra air is ~8px on the tile, which is
          breathing room rather than a second section. */}
      <div className="flex flex-1 flex-col gap-1.5 px-0.5 pt-2.5">
        {/* 14px semibold off-white - the same step as the rest of the app's
            body text, but the only semibold thing above the price, so the
            name is what a collector reads first after the artwork. */}
        <span className="truncate text-sm font-semibold leading-snug text-text-primary">
          {print.displayName}
        </span>

        {/* The Japanese name is kept where it adds something: the English name
            is now the display name for almost every card, so the JP line is
            the collector's link back to what is printed on the card itself.
            Suppressed when they are the same string, which is what a card
            with no English name yet renders. */}
        {print.nameJp && print.nameJp !== print.displayName && (
          <span className="truncate text-[11px] leading-none text-text-muted">
            {print.nameJp}
          </span>
        )}

        <div className="mono flex flex-wrap items-center gap-x-1.5 text-[10px] leading-none text-text-muted">
          <span>{print.cardCode}</span>
          {print.releaseCode && (
            <>
              <span aria-hidden="true">·</span>
              {/* "Found in", not "Set": for a reprint this product is a later
                  release than the set the card came from. */}
              <span>
                <span className="text-text-faint">Found in </span>
                {print.releaseCode}
              </span>
            </>
          )}
        </div>

        {/* Three independent facts, in the order the detail page states them:
            how scarce the card is, whether this printing is a special
            category, and which printing it is. They read left to right from
            the card's own property to this item's, and a print is commonly
            two or three of them at once - a Super Rare that is also an SP
            Card and an Alt Art is not a contradiction, which is exactly what
            keeping the chips separate says.

            Together they are also what keeps two sibling prints of one card
            apart at a glance. The base printing shows no printing badge - its
            absence is the signal. The art ordinal appears only when even
            these leave two tiles reading identically. */}
        <div className="flex min-h-[18px] flex-wrap items-center gap-1.5">
          {print.rarityTerm && <RarityTermBadge term={print.rarityTerm} />}
          {print.specialPrint && <SpecialPrintBadge term={print.specialPrint} />}
          {print.unknownRarityToken && <UnknownRarityBadge token={print.unknownRarityToken} />}
          {printingType && (
            <span
              className="mono inline-flex rounded border border-accent-gold/30 bg-accent-gold/10 px-1.5 py-px text-[10px] font-medium tracking-wide text-accent-gold"
              title={`${printingType.label} — ${printingType.definition}`}
            >
              {printingType.label}
            </span>
          )}
          {artOrdinal && (
            <span className="mono inline-flex rounded border border-border-muted px-1.5 py-px text-[10px] font-medium tracking-wide text-text-muted">
              {artOrdinal}
            </span>
          )}
        </div>

        {/* Caption stacked over the value, not inline beside it: inline made
            the two compete for one 20px line and the index read as another
            metadata row. Stacked, the muted caption names the number and the
            gold number is the only thing at that size in the lower block, so
            it is the monetary focal point without becoming a price block
            bigger than the artwork. */}
        <div className="mt-auto pt-3">
          <span className="mono block text-[10px] font-medium uppercase leading-none tracking-[0.14em] text-text-muted">
            Market Index
          </span>
          <div className="mt-1.5">
            <MarketIndexValue
              index={print.marketIndex}
              size="base"
              tone="gold"
              // Coverage is stated by the per-source rows below, which carry
              // strictly more information than the chip would.
              showCoverage={false}
            />
          </div>
          <SourcePrices print={print} />
        </div>
      </div>
    </Link>
  );
}

/** The real per-source prices already sitting in this print's own
 * `market_index.source_values` (see toPrintUiModel) - never a second request,
 * never a sibling's price, never a placeholder for a source that reported
 * nothing.
 *
 * SOURCE-AGNOSTIC BY CONSTRUCTION. This function names no source. It maps the
 * payload's own `source_values`, in the order the API sent them, and asks
 * `sourceDisplayName` what to call each one - which returns the API's raw key
 * unchanged for a source this build has never heard of, so a Card Rush or
 * Cardmarket value added server-side appears here as a real row with a real
 * price on the day it ships, rather than silently vanishing until someone
 * remembers to edit this file. It used to read two hardcoded fields, which
 * meant a third source was a rewrite; the tile is now the same amount of code
 * for two sources or five.
 *
 * ALWAYS SHOWN. A source that reported a price gets a row even when its value
 * equals the Market Index above it. That repetition was previously suppressed
 * as redundant, and the suppression cost more than it saved: a one-source
 * print then showed a gold figure with no provenance at all, which is exactly
 * the tile where a collector most needs to know WHOSE price they are looking
 * at. "Market Index ¥14,000 / Yuyu-Tei ¥14,000 / Retail price" says one number
 * twice and one fact - which shop - once, and the fact is worth the line.
 *
 * A source with `value_jpy: null` gets a row that NAMES it and says "Price
 * unavailable" - never ¥0, never a dash, never a blank cell where a price
 * goes. Dropping it silently made a one-priced-source tile indistinguishable
 * from a tile whose second retailer had never been asked, which is the one
 * thing a collector comparing two shops needs to be able to tell apart. The
 * absence rows follow the priced ones so the prices stay the top of the block,
 * and they appear only when some other source on this print did report a
 * number - see @/lib/sourceAvailability. When NO source reported, the block
 * collapses entirely, leaving MarketIndexValue's "Index unavailable" as the
 * only claim on the tile rather than one negative per source beneath it.
 *
 * Laid out as a caption-over-price comparison so the retailers can be read
 * against each other at a glance, with the price the legible half and the
 * retailer name the small one. The column count follows the number of sources
 * that actually reported, capped at two per row so a third source wraps rather
 * than crushing the prices into unreadable slivers on a 390px phone.
 *
 * Sizing is deliberately the same at every viewport: the price is 13px and
 * the retailer name 10px on a 390px phone exactly as on a 1440px desktop.
 * These numbers are the collector information the whole tile exists to carry,
 * and shrinking them on the surface most people browse on is what made them
 * read as footnotes.
 *
 * The price never truncates. Its column is ~72px on a 390px-wide two-column
 * catalogue, which holds a seven-figure yen value at 13px, and anything
 * somehow wider wraps rather than clips - a half-shown price is a wrong
 * price, which this product must never render. The source *name* may
 * truncate: it is a known constant and cannot be misread as a number.
 */
function SourcePrices({ print }: { print: PrintUiModel }) {
  const sources = print.marketIndex.source_values;
  // Priced rows first, then the sources that reported nothing. The second
  // list is empty unless the first one is not - so this collapses to exactly
  // the old behaviour on a print no source priced.
  const rows = [...displayedSourceValues(sources), ...unavailableSourceValues(sources)];
  if (rows.length === 0) return null;

  return (
    <dl
      className={`mt-2.5 grid gap-x-2 gap-y-2 border-t border-border-muted pt-2 ${
        rows.length > 1 ? "grid-cols-2" : "grid-cols-1"
      }`}
    >
      {rows.map((row) => (
        <div key={`${row.source}-${row.reference_type}`} className="min-w-0">
          <dt className="mono truncate text-[10px] uppercase leading-none tracking-[0.08em] text-text-muted">
            {sourceDisplayName(row.source)}
          </dt>
          {/* A statement of absence, written as a sentence and set in the
              muted colour at the ordinary text size - deliberately NOT the
              tabular mono treatment a price gets, so it can never be scanned
              as a number-shaped thing in the price column. */}
          {isUnavailableSourceValue(row) ? (
            <dd className="mt-1.5 text-[11px] leading-tight text-text-muted">
              {SOURCE_PRICE_UNAVAILABLE_LABEL}
            </dd>
          ) : (
            <>
              <dd className="mono tabular mt-1.5 break-words text-[13px] font-medium leading-none text-text-primary">
                {formatJpy(row.value_jpy)}
              </dd>
              {/* What KIND of price this is - "Retail price", "Current listing",
                  "Recent sales median". Neutral supporting text in the muted
                  colour, never a warning: under Market Index v3 an eligible
                  current listing counts toward the index exactly like a sold
                  median, so this describes the evidence rather than qualifying it.
                  The one-sentence explanation behind each label lives on the print
                  detail page: the whole tile is a single <Link>, and a disclosure
                  button nested inside an anchor is invalid HTML that misbehaves on
                  both keyboard and touch. */}
              <dd className="mt-1 text-[9px] leading-tight text-text-muted">
                {sourceEvidenceLabel(row.reference_type)}
              </dd>
              {/* A price the index was not computed from. Under v3 this can only
                  be an EXCLUDED value - a platform-minimum listing, a stale
                  observation - because every eligible value now contributes, so
                  the line no longer appears beside perfectly ordinary prices the
                  way it did under v2. Two words at 9px in the muted colour: enough
                  that an excluded row is not read as disagreement with the index,
                  small enough that it never competes with the price above it. */}
              {isReferenceOnly(row) && (
                <dd className="mt-1 text-[9px] leading-tight text-text-muted">
                  {REFERENCE_ONLY_LABEL}
                </dd>
              )}
            </>
          )}
        </div>
      ))}
    </dl>
  );
}
