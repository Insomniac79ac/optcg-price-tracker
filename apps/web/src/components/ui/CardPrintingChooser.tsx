"use client";

import { useMemo } from "react";

import { CardGrid } from "@/components/ui/CardGrid";
import { CardGridSkeleton } from "@/components/ui/CardGridSkeleton";
import { PrintCardTile } from "@/components/ui/PrintCardTile";
import { printsNeedingArtOrdinal, type PrintUiModel } from "@/lib/prints";

/** The bridge from a card to the exact printing a collector actually owns.
 *
 * WHY THIS SECTION EXISTS. A legacy `cards` row is one card *code*; the thing
 * a collector owns, values and sells is one PRINTING of it, and two printings
 * of the same card are separately-priced collectibles (see lib/prints.ts).
 * Everything price-shaped on this page is therefore card-level and merged
 * across printings; the honest resolution is to hand the reader the list and
 * let them pick, not to guess which printing they meant.
 *
 * It never chooses for them. A card with one printing still renders that
 * printing as an option rather than redirecting, because "this card has
 * exactly one printing" is itself information, and a redirect would hide it.
 *
 * WHAT IT DOES NOT DO. No price is computed, compared, ranked or filtered
 * here. Each tile renders the print-scoped Market Index the API already
 * attached to that print, through the same `MarketIndexValue` the catalogue
 * uses - including its "Index unavailable" state, which is what a printing
 * with no eligible source shows. This is a navigation surface.
 *
 * IDENTITY COMES FROM THE PRINTS, NOT THE CARD ROW. `canonicalName` is
 * resolved by `resolveCanonicalPrintIdentity` from the very records rendered
 * below, and is null whenever they do not unanimously agree. The legacy
 * `cards` row is never consulted: 10 of 25 staging rows name a different
 * character than the canonical card their `card_code` resolves to, and this
 * heading is precisely where that would mislabel a whole set of printings.
 * With no agreed name the header shows the card code alone - the one
 * identifier both sides agree on - rather than picking a winner.
 */
export type PrintingChooserStatus = "loading" | "error" | "ready";

export function CardPrintingChooser({
  status,
  prints,
  cardCode,
  canonicalName,
}: {
  status: PrintingChooserStatus;
  prints: PrintUiModel[];
  /** The card code these printings share - always shown, always trusted. */
  cardCode: string;
  /** The canonical name, when every record agreed on one. Null otherwise, and
   * the header then carries the code alone. Never the legacy card's name. */
  canonicalName: string | null;
}) {
  // Scoped to the prints shown together, exactly as the catalogue grid scopes
  // it: an ordinal earns its place only when two tiles on THIS page would
  // otherwise read identically - which is common here, since every tile is a
  // printing of the same card and shares its name, code and product.
  const ordinalNeeded = useMemo(() => printsNeedingArtOrdinal(prints), [prints]);

  return (
    <section className="rounded-panel border border-border-default bg-bg-surface p-4">
      <h2 className="text-sm font-semibold text-text-primary">
        Printings of{" "}
        {canonicalName ? (
          <>
            {canonicalName}{" "}
            <span className="mono font-normal text-text-muted">{cardCode}</span>
          </>
        ) : (
          <span className="mono">{cardCode}</span>
        )}
      </h2>
      <p className="mt-1 text-xs text-text-secondary">
        Each printing of this card is valued separately. Choose the one you
        have to see its Market Index and price history.
      </p>

      <div className="mt-3">
        {status === "loading" && <CardGridSkeleton count={3} />}

        {status === "error" && (
          <p className="text-sm text-text-muted">
            The printings of this card couldn’t be loaded right now.
          </p>
        )}

        {status === "ready" && prints.length === 0 && (
          <p className="text-sm text-text-muted">
            No printings of this card have been catalogued yet.
          </p>
        )}

        {status === "ready" && prints.length > 0 && (
          <CardGrid>
            {prints.map((print) => (
              <PrintCardTile
                key={print.cardPrintId}
                print={print}
                showArtOrdinal={ordinalNeeded.has(print.cardPrintId)}
              />
            ))}
          </CardGrid>
        )}
      </div>
    </section>
  );
}
