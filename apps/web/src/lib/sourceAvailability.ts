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
 * DERIVES NOTHING. This module reads `value_jpy` and nothing else. It does not
 * consult `eligible`, `contributes_to_index`, `constraint` or `stale`, does
 * not count sources, and is not consulted by anything that does: `source_count`,
 * the contribution qualifier (@/lib/sourceContribution) and `source_price_range`
 * are all the backend's own published facts and are unchanged by whether an
 * absence is drawn on screen. An unavailable row has no price to qualify, so it
 * carries no evidence label, no constraint note and no contribution note -
 * those describe what a number IS, and there is no number here.
 */

/** The one place the collector-facing wording for a missing price lives. */
export const SOURCE_PRICE_UNAVAILABLE_LABEL = "Price unavailable";

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
