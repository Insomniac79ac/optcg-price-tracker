/** Naming a source that reported no price at all, without inventing one.
 *
 * THE DISHONESTY THIS FIXES. `market_index.source_values` carries an entry for
 * every source the backend asked, including the ones that answered nothing -
 * `value_jpy: null`, `ineligible_reason: "no_observation"`. Both collector
 * surfaces used to drop those entries silently, so a print with a Yuyu-Tei
 * price and no SNKRDUNK price rendered exactly like a print SNKRDUNK had never
 * been asked about: one row, one retailer, no statement either way. A reader
 * comparing two shops was left to assume the second shop agreed, or had been
 * omitted for some editorial reason, or did not exist. The missing half of the
 * comparison was the fact they most needed.
 *
 * WHAT IS SAID INSTEAD. The source is named and its price line reads "Price
 * unavailable". Not ¥0, not a dash, not "-", not an empty cell: every one of
 * those is a number-shaped thing sitting where a price goes, and this product
 * must never render a number it does not have. The row is a *statement of
 * absence*, which is a different claim from a low price and is written as a
 * sentence so it can never be misread as one.
 *
 * THE ONE PRECONDITION. An unavailable row appears only when some other source
 * on the same print did report a number. That is the whole reason the row
 * exists: it exists to complete a comparison the reader can already see half
 * of. Where NO source reported, there is no comparison to complete - the
 * Market Index itself already says "Index unavailable", and listing every
 * known source underneath it saying "Price unavailable" would restate that one
 * fact once per source and turn a clean empty state into a wall of negatives.
 *
 * WHICH ROWS ARE ABSENCES DERIVES FROM `value_jpy` AND NOTHING ELSE. This
 * module does not consult `eligible`, `contributes_to_index`, `constraint` or
 * `stale` to decide that, does not count sources, and is not consulted by
 * anything that does: `source_count`, the contribution qualifier
 * (@/lib/sourceContribution) and `source_price_range` are all the backend's own
 * published facts and are unchanged by whether an absence is drawn on screen.
 * An unavailable row has no price to qualify, so it carries no evidence label,
 * no constraint note and no contribution note - those describe what a number
 * IS, and there is no number here.
 *
 * WHAT THE ABSENCE SAYS IS A SECOND QUESTION, and `describeUnavailableSource`
 * below is the only place it is answered - see its own docstring for why one
 * absence deserves different words from the rest.
 */

/** The one place the collector-facing wording for a missing price lives.
 *
 * The default, and still the right words wherever the backend has not told us
 * anything more specific: it claims only that no price is being shown. */
export const SOURCE_PRICE_UNAVAILABLE_LABEL = "Price unavailable";

/** The wording for a source that looked and found nothing on offer.
 *
 * "Price unavailable" is honest but ambiguous - it covers "we could not get a
 * price" and "there is no price to get", and a collector cannot tell which. On
 * SNKRDUNK the backend can distinguish them, so where it does, the stronger
 * and more useful sentence is said instead. */
export const SOURCE_NO_LISTING_LABEL = "No current listing";

/** What an unavailable row says: the line itself, and the one sentence behind
 * it when there is more to explain than the line can carry. */
export interface UnavailableSourceCopy {
  label: string;
  /** A single plain sentence for an InfoTip disclosure, or null when the label
   * stands alone and needs no expansion. Text only - see InfoTip. */
  explanation: string | null;
}

/** The absences the backend can name precisely, keyed on the reason it
 * published.
 *
 * KEYED ON `ineligible_reason`, NEVER ON THE SOURCE NAME PLUS A NULL PRICE.
 * "snkrdunk with no number" is true of several genuinely different situations -
 * the collector has not reached this mapping yet, the page failed to load, the
 * observation aged out - and only the backend knows which one happened.
 * `insufficient_sold_and_no_floor` is `market_index._resolve_snkrdunk`'s own
 * verdict that it looked at the product and found neither a sufficient sold
 * sample nor any listing floor: the source answered, and the answer was "nobody
 * is selling this right now". Guessing that from the source's name would state
 * it for every other reason too, including the ones that mean the opposite.
 *
 * `source` is recorded beside the copy because the sentence NAMES SNKRDUNK. The
 * reason is what identifies the state; the source check is what keeps a
 * sentence about SNKRDUNK from being printed under some future source that
 * happens to report the same reason. Both must match, and an unrecognised
 * reason falls through to the generic wording rather than to a guess.
 */
const UNAVAILABLE_SOURCE_COPY: Record<
  string,
  { source: string; copy: UnavailableSourceCopy }
> = {
  insufficient_sold_and_no_floor: {
    source: "snkrdunk",
    copy: {
      label: SOURCE_NO_LISTING_LABEL,
      explanation:
        "No active listing was observed on SNKRDUNK. This does not necessarily " +
        "mean the card has low value; there may simply be no seller listing it " +
        "individually right now.",
    },
  },
};

/** What to write in place of a price for one absent row.
 *
 * Only meaningful for a row `isUnavailableSourceValue` returns true for;
 * callers branch on that first and this never sees a priced row. It still
 * checks `value_jpy === null` itself, so the specific wording cannot escape
 * onto a row that has a number - a ¥1,000 platform-floor listing is a PRICE
 * with a constraint, keeps every word of its existing constraint copy, and is
 * never routed through here.
 *
 * Falls back to `SOURCE_PRICE_UNAVAILABLE_LABEL` for every other absence,
 * including `no_observation`, a null/absent reason, and any reason a future
 * backend adds that this build has not been taught. That fallback is the point:
 * an unknown reason means we do not know why the price is missing, and the
 * generic line is the only claim still true.
 */
export function describeUnavailableSource(value: {
  source: string;
  value_jpy: number | null;
  ineligible_reason?: string | null;
}): UnavailableSourceCopy {
  const generic: UnavailableSourceCopy = {
    label: SOURCE_PRICE_UNAVAILABLE_LABEL,
    explanation: null,
  };
  if (value.value_jpy !== null) return generic;
  if (!value.ineligible_reason) return generic;

  const entry = UNAVAILABLE_SOURCE_COPY[value.ineligible_reason];
  if (!entry || entry.source !== value.source) return generic;
  return entry.copy;
}

/** The sources that reported nothing and are worth naming anyway, in the
 * order the API sent them.
 *
 * Empty unless at least one OTHER source on this print carries a number - see
 * "THE ONE PRECONDITION" above. Callers render these after the priced rows, so
 * the prices stay the top of the block and the absences read as the completion
 * of the list rather than as its subject. */
export function unavailableSourceValues<T extends { value_jpy: number | null }>(
  sources: T[],
): T[] {
  const hasNumericPrice = sources.some((entry) => entry.value_jpy !== null);
  if (!hasNumericPrice) return [];
  return sources.filter((entry) => entry.value_jpy === null);
}

/** True for a row that must be drawn as an absence rather than a price.
 *
 * Callers hold one combined list - priced rows then unavailable ones - and ask
 * this per row rather than tracking a parallel flag, so the two halves can
 * never drift out of step with each other. */
export function isUnavailableSourceValue(value: { value_jpy: number | null }): boolean {
  return value.value_jpy === null;
}
