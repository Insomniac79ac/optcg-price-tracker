import Link from "next/link";

import { RarityBadge } from "@/components/RarityBadge";
import { formatDate } from "@/lib/format";
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
 * Hierarchy is artwork first, then identity, then price, then source
 * evidence - the collector-UI skill's ordering. Everything the API returns
 * but a collector doesn't need mid-browse (card type, language, confidence,
 * verification status) is deliberately left off the tile.
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
      className="vault-card group flex flex-col overflow-hidden rounded-panel focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-gold focus-visible:ring-offset-2 focus-visible:ring-offset-bg-page"
    >
      <CardImageFrame
        imageUrl={print.imageUrl}
        alt={`${print.displayName} (${print.cardCode})`}
        cardCode={print.cardCode}
        rarity={print.rarity}
        setCode={print.releaseCode}
        size="full"
        padded
      />

      <div className="flex flex-1 flex-col gap-1.5 p-2.5">
        <div className="flex items-start justify-between gap-1.5">
          <span className="truncate text-sm font-medium text-text-primary">
            {print.displayName}
          </span>
          {print.rarity && <RarityBadge rarity={print.rarity} />}
        </div>

        <div className="mono flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-text-muted">
          <span>{print.cardCode}</span>
          {print.releaseCode && (
            <>
              <span aria-hidden="true">·</span>
              <span>{print.releaseCode}</span>
            </>
          )}
          {treatmentLabel && (
            <>
              <span aria-hidden="true">·</span>
              <span className="normal-case text-accent-gold">{treatmentLabel}</span>
            </>
          )}
        </div>

        <div className="mt-auto pt-1.5">
          <MarketIndexValue
            index={print.marketIndex}
            size="sm"
            sourceNames={print.contributingSources}
          />
          {print.latestObservationAt && (
            <div className="mt-1 text-[10px] text-text-faint">
              Updated {formatDate(print.latestObservationAt)}
            </div>
          )}
        </div>
      </div>
    </Link>
  );
}
