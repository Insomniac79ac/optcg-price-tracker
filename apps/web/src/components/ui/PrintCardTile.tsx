import Link from "next/link";

import { RarityBadge } from "@/components/RarityBadge";
import { formatJpy } from "@/lib/format";
import type { PrintUiModel } from "@/lib/prints";
import { CardImageFrame } from "./CardImageFrame";
import { MarketIndexValue } from "./MarketIndexValue";

/** One collectible print in the public catalogue grid.
 *
 * The print-centric counterpart to CollectorCardTile, which stays on the
 * legacy card_id-keyed `CardCatalogueItem` for the pages that still use it.
 * This one is keyed by `card_print_id` end to end - its link, its React key,
 * and its price all belong to exactly one print, so a base and a parallel
 * that bridge through the same legacy card render as two independent tiles
 * with two independent prices.
 *
 * Hierarchy is artwork, then name, then code/set, then treatment + rarity,
 * then Market Index, then the sources behind it - the collector-UI skill's
 * ordering. Everything the API returns but a collector doesn't need
 * mid-browse (card type, language, confidence, verification status) is
 * deliberately left off the tile.
 *
 * The artwork is the only thing here with any real colour: the tile itself is
 * a charcoal surface with a hairline border and no gradient, glow or frame
 * ornament, so a wall of these reads as a wall of *cards*. The one accent is
 * gold on the Market Index; teal appears only on hover/focus.
 *
 * Every value shown comes from this print's own catalogue payload. Nothing
 * here fetches, and nothing is derived from a sibling print.
 */
export function PrintCardTile({ print }: { print: PrintUiModel }) {
  const treatmentLabel = print.isDistinctTreatment ? print.treatment : null;
  const accessibleName = [
    print.displayName,
    print.cardCode,
    treatmentLabel,
    print.releaseCode,
    print.rarity,
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

        <div className="mono flex flex-wrap items-center gap-x-1.5 text-[10px] leading-none text-text-muted">
          <span>{print.cardCode}</span>
          {print.releaseCode && (
            <>
              <span aria-hidden="true">·</span>
              <span>{print.releaseCode}</span>
            </>
          )}
        </div>

        {/* Treatment sits with rarity rather than in the code row, because it
            is the one thing that keeps two sibling prints of the same card
            apart at a glance. Only ever the API's own string ("parallel"),
            never renamed or inferred - and the plain base printing shows
            nothing here, which is what makes the parallel beside it read as
            the different one. */}
        <div className="flex min-h-[18px] items-center gap-1.5">
          {treatmentLabel && (
            <span className="mono inline-flex rounded border border-accent-gold/30 bg-accent-gold/10 px-1.5 py-px text-[10px] font-medium lowercase tracking-wide text-accent-gold">
              {treatmentLabel}
            </span>
          )}
          {print.rarity && <RarityBadge rarity={print.rarity} />}
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
