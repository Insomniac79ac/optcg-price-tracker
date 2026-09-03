/** Which visible source prices actually went into Market Index.
 *
 * Market Index v2 split two questions that used to share one answer: whether
 * a value is admissible evidence (`eligible`) and whether it went into the
 * number (`contributes_to_index`). A SNKRDUNK listing floor whose
 * `fallback_used` is true stays eligible, keeps its raw price and stays
 * inside `source_price_range`, but stands aside from the aggregate whenever a
 * non-fallback source is present. The print page had no way to say that: a
 * ¥2,500 SNKRDUNK price sat beside a ¥120 index with nothing on screen
 * explaining how both could be true at once.
 *
 * This is NOT a source constraint. `platform_floor`, `below_platform_minimum`
 * and `sale_price` say why a price may not mean what its number says; they
 * live in @/lib/sourceConstraint and keep their own wording. Contribution
 * answers a different question - did this number feed the index - and a
 * fallback source can be perfectly trustworthy data while still not
 * contributing. The two concepts are therefore kept apart here rather than
 * folded into one badge vocabulary.
 *
 * `contributes_to_index` is the ONLY input. It arrives decided by
 * app.services.market_index and nothing in this module re-derives it from
 * `eligible`, `fallback_used`, the source's name, the size of the price,
 * `source_count`, or any threshold - a second opinion in the browser is
 * exactly how the two would drift apart.
 *
 * The wire type is `bool | None`, and the three states are not two: `false`
 * means "did not contribute", while absent/null means "this payload predates
 * the field" and must never be read as an exclusion. Every predicate below
 * tests `=== false` explicitly and so fails closed - an older API renders
 * exactly what it rendered before.
 */

/** Chip label for a visible price that did not feed the index. */
export const REFERENCE_ONLY_LABEL = "Reference only";

/** The one sentence under that chip. Says what the price *is* for rather than
 * what is wrong with it, because nothing is wrong with it. */
export const REFERENCE_ONLY_EXPLANATION =
  "Shown for context; not used in Market Index.";

/** Caption under the source range when the span covers a reference-only
 * price. `source_price_range` is computed from every ADMISSIBLE value, before
 * the contributor filter (see market_index.py), so a one-source index beside
 * a two-endpoint range is correct and this line is what makes it legible. */
export const REFERENCE_ONLY_RANGE_CAPTION =
  "Includes reference-only source prices.";

/** The subset of a source value this module reads. Structural rather than a
 * concrete import so both the print-scoped and card-scoped shapes satisfy it. */
export interface ContributableSourceValue {
  value_jpy: number | null;
  eligible: boolean;
  contributes_to_index?: boolean | null;
}

/** True only when the backend explicitly said this value did not contribute.
 * Absent/null is not an exclusion - see the module docstring. */
export function isReferenceOnly(value: {
  contributes_to_index?: boolean | null;
}): boolean {
  return value.contributes_to_index === false;
}

/** The source values that appear on screen as a price at all. A source that
 * reported nothing has no panel, no tile row and no place in any count here. */
export function displayedSourceValues<T extends { value_jpy: number | null }>(
  sources: T[],
): T[] {
  return sources.filter((entry) => entry.value_jpy !== null);
}

/** "1 of 2 source prices used", or null when there is nothing to qualify.
 *
 * THE NUMERATOR IS THE BACKEND'S OWN `source_count` AND NOTHING ELSE. How
 * many values went into the aggregate is a fact app.services.market_index
 * already computed and published; counting the ones this build believes were
 * not excluded would be a second implementation of the contributor rule,
 * living in a browser, free to disagree with the number it sits beneath. It
 * would also be silently wrong against any payload whose `contributes_to_index`
 * this build cannot read - an older API, or a future role the v2 filter grows.
 *
 * The denominator is what the reader can actually see: source values carrying
 * a price, which is exactly the set that gets a panel. So the sentence
 * compares the index's own stated input count against the prices on screen,
 * and both halves come from the payload.
 *
 * Null when the two agree - every visible price is accounted for and the line
 * would only restate the panels. Note that no index value is required: a
 * print whose only price is an excluded platform floor reports
 * `source_count = 0` beside one visible price, and "0 of 1 source prices used"
 * is precisely the thing that explains an unavailable index. */
export function contributionQualifier(index: {
  source_count: number;
  source_values: ContributableSourceValue[];
}): string | null {
  const displayed = displayedSourceValues(index.source_values).length;
  if (displayed <= index.source_count) return null;

  return `${index.source_count} of ${displayed} source prices used`;
}

/** Whether the source range spans a price that did not feed the index.
 *
 * Requires `eligible` as well: the range is built from admissible values, so
 * an ineligible price (a below-minimum anomaly, say) is not inside it and a
 * caption claiming otherwise would be false. */
export function rangeIncludesReferenceOnly(
  sources: ContributableSourceValue[],
): boolean {
  return displayedSourceValues(sources).some(
    (entry) => entry.eligible && isReferenceOnly(entry),
  );
}
