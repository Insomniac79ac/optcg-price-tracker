/** What KIND of evidence a source value is, in a collector's words.
 *
 * The API's `reference_type` (see the resolvers in
 * services/api/app/services/market_index.py) names the quantity a source
 * reported: a shop's displayed selling price, the median of a marketplace's
 * recent completed sales, the cheapest listing currently open on it, a
 * dealer's standing buy offer. Those are four genuinely different claims about
 * a card and this module is the one place that turns each into a phrase and a
 * sentence, so the copy can change or be translated without touching a page.
 *
 * NEUTRAL BY CONSTRUCTION. Under Market Index v3 every eligible source value
 * contributes to the index regardless of its evidence type - a current asking
 * price is weaker and different evidence from a completed sale, but it is not
 * an error and not a caveat. So there is no `tone` here, no amber, and nothing
 * a caller could render as a warning: describing what a number IS is not the
 * same as saying something is wrong with it. Where something IS wrong with a
 * value - a platform-minimum listing, a below-minimum anomaly, a stale
 * observation - that stays with @/lib/sourceConstraint and its own vocabulary,
 * which this module neither duplicates nor softens.
 *
 * `reference_type` is the ONLY input. Nothing here inspects the source's name,
 * its price, `fallback_used`, or whether the value contributed. A future Card
 * Rush or Cardmarket retail price is labelled by the same entry that labels
 * Yuyu-Tei's, because it reports the same kind of thing.
 */

export interface SourceEvidenceCopy {
  /** Short phrase shown beside or beneath the price. */
  label: string;
  /** One plain-English sentence, for a tooltip/popover. Says what the number
   * is and, where it matters, what it is not. */
  explanation: string;
}

const SOURCE_EVIDENCE_COPY: Record<string, SourceEvidenceCopy> = {
  // Yuyu-Tei's displayed sell price. "Retail price" rather than "Retail sell
  // price": the shop sells, the collector buys, and the collector's word for
  // the number on the shelf is the price.
  retail_sell: {
    label: "Retail price",
    explanation:
      "The price this shop is currently selling the card for. Asking prices are not completed sales and may differ from the price a card ultimately sells for.",
  },
  // SNKRDUNK's median of recent completed sales - the strongest evidence any
  // source currently reports, and the only reference type that describes
  // transactions that actually happened.
  transaction_median: {
    label: "Recent sales median",
    explanation:
      "The middle price of this source's recent completed sales - what the card has actually been changing hands for, rather than what it is being asked for.",
  },
  // The cheapest listing currently open on a marketplace. The explanation is
  // the product decision's own wording, kept verbatim: it is the one place
  // this app promises a collector that an asking price is not a sale.
  listing_floor: {
    label: "Current listing",
    explanation:
      "Lowest current listing observed on this source. Asking prices are not completed sales and may differ from the price a card ultimately sells for.",
  },
  // Auxiliary only - a dealer's standing offer to buy, which is never a
  // candidate for the index. The sentence says so, because this is the one
  // reference type where "not used in Market Index" is a property of the
  // evidence type itself rather than of anything wrong with the value.
  dealer_buy: {
    label: "Dealer buy price",
    explanation:
      "What this shop currently offers to pay for the card. Shown for context only; buy prices never count toward Market Index.",
  },
};

/** The copy for one `reference_type`, or null when this build has never heard
 * of it.
 *
 * Null is the honest answer for a reference type a future backend adds:
 * inventing a sentence about a quantity this build cannot identify would state
 * something it does not know. Callers fall back to showing the API's own
 * string with no explanation, which names the value without claiming anything
 * about it. */
export function describeSourceEvidence(
  referenceType: string | null | undefined,
): SourceEvidenceCopy | null {
  if (!referenceType) return null;
  return SOURCE_EVIDENCE_COPY[referenceType] ?? null;
}

/** The label alone, with the API's raw string as the last resort - the same
 * "pass an unknown identifier through rather than invent a label" rule
 * sourceDisplayName uses for source names. */
export function sourceEvidenceLabel(referenceType: string): string {
  return describeSourceEvidence(referenceType)?.label ?? referenceType;
}

/** A `reference_type` in a collector's words, or null when there is no
 * instrument to name.
 *
 * The nullable counterpart to `sourceEvidenceLabel`, and the one every
 * *series* label is built from - the chart's chips and legend
 * (@/lib/printSeries) and the evidence rows beneath it
 * (@/lib/printPriceHistory) both come here, so one quantity is one word
 * wherever it appears.
 *
 * Null is not a failure. A source whose instrument the server did not name -
 * absent, empty, or a series whose instrument changed mid-history - has no
 * single word for what it measures, and the caller names the platform alone
 * rather than claiming one.
 *
 * An instrument this build has never heard of is HUMANISED, not guessed at:
 * `auction_high` becomes "Auction high", which states the server's own token
 * without asserting what it measures. Nothing here inspects a source name, a
 * price, or a stored `price_type`: a future Card Rush / Cardmarket instrument
 * is labelled by the server's word for it, with no release on this side. */
export function instrumentLabel(referenceType: string | null | undefined): string | null {
  if (!referenceType) return null;
  const known = describeSourceEvidence(referenceType);
  if (known) return known.label;
  const opened = referenceType.replace(/_/g, " ").trim();
  if (opened === "") return null;
  return opened.charAt(0).toUpperCase() + opened.slice(1);
}
