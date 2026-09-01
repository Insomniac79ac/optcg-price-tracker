import Link from "next/link";

import { RarityTermBadge, SpecialPrintBadge, UnknownRarityBadge } from "@/components/RarityBadge";
import { formatJpy } from "@/lib/format";
import { isRedundantSingleSource, type PrintUiModel } from "@/lib/prints";
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
 * A source only appears when it actually contributed a value, so the rows
 * *are* the coverage statement: two rows is a two-source index, one row is a
 * one-source index and cannot be mistaken for a consensus. When the index
 * itself is unavailable there is nothing to list and the block collapses,
 * leaving MarketIndexValue's "Index unavailable" as the only claim.
 *
 * Laid out as a caption-over-price comparison so the two retailers can be
 * read against each other at a glance, with the price the legible half and
 * the retailer name the small one. The column count is the number of sources
 * that actually reported, not a fixed two - a one-source print gets a single
 * column rather than a half-empty grid that would read as a missing figure.
 * A hairline rule separates the sources from the index they produced; there
 * is deliberately no box around either source.
 *
 * Sizing is deliberately the same at every viewport: the price is 13px and
 * the retailer name 10px on a 390px phone exactly as on a 1440px desktop.
 * These two numbers are the collector information the whole tile exists to
 * carry, and shrinking them on the surface most people browse on is what
 * made them read as footnotes.
 *
 * The price never truncates. Its column is ~72px on a 390px-wide two-column
 * catalogue, which holds a seven-figure yen value at 13px, and anything
 * somehow wider wraps rather than clips - a half-shown price is a wrong
 * price, which this product must never render. The source *name* may
 * truncate: it is one of two known constants and cannot be misread as a
 * number.
 */
function SourcePrices({ print }: { print: PrintUiModel }) {
  // A lone eligible, unconstrained source whose value IS the index adds
  // nothing the gold figure above has not already said - see
  // isRedundantSingleSource for the four conditions, all of which must hold.
  // A constrained source, an ineligible one, a differing value, or a second
  // retailer all keep their rows.
  if (isRedundantSingleSource(print.marketIndex)) return null;

  const rows = [
    { name: "Yuyu-Tei", value: print.yuyuteiJpy },
    { name: "SNKRDUNK", value: print.snkrdunkJpy },
  ].filter((row): row is { name: string; value: number } => row.value !== null);

  if (rows.length === 0) return null;

  return (
    <dl
      className={`mt-2.5 grid gap-x-2 border-t border-border-muted pt-2 ${
        rows.length > 1 ? "grid-cols-2" : "grid-cols-1"
      }`}
    >
      {rows.map((row) => (
        <div key={row.name} className="min-w-0">
          <dt className="mono truncate text-[10px] uppercase leading-none tracking-[0.08em] text-text-muted">
            {row.name}
          </dt>
          <dd className="mono tabular mt-1.5 break-words text-[13px] font-medium leading-none text-text-primary">
            {formatJpy(row.value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}
