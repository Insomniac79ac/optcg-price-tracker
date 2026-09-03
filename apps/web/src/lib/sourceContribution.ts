/** Which visible source prices actually went into Market Index.
 *
 * Market Index v2 split two questions that used to share one answer: whether a
 * value is admissible evidence (`eligible`) and whether it went into the number
 * (`contributes_to_index`). Under v2 the two could genuinely disagree - an
 * eligible SNKRDUNK listing floor kept its raw price and its place in
 * `source_price_range` while standing aside from the aggregate - and this
 * module exists because the print page had no way to say that: a ¥2,500
 * SNKRDUNK price sat beside a ¥120 index with nothing on screen explaining how
 * both could be true at once.
 *
 * UNDER v3 THAT DISAGREEMENT NO LONGER ARISES. Every admissible value
 * contributes, so a v3 backend reports `contributes_to_index: false` only for a
 * value that is ALSO ineligible - constrained, stale or absent - and those
 * already carry the more specific explanation in @/lib/sourceConstraint, which
 * is why the "Reference only" chip is silent for them (see
 * SourceContributionNote). The result is that an eligible current listing is no
 * longer marked at all, which is the intended v3 outcome: it counts, so there
 * is nothing to qualify.
 *
 * This module is kept, unchanged in logic, for the two cases where the
 * distinction still has work to do: an API that predates the v3 deploy and is
 * still applying the v2 role filter, and any future role the backend may
 * introduce. Both are handled by reading the published field and nothing else.
 *
 * This is NOT a source constraint. `platform_floor`, `below_platform_minimum`
 * and `sale_price` say why a price may not mean what its number says; they
 * live in @/lib/sourceConstraint and keep their own wording. Contribution
 * answers a different question - did this number feed the index - and under v2
 * a source could be perfectly trustworthy data while still not contributing.
 * The two concepts are therefore kept apart here rather than folded into one
 * badge vocabulary.
 *
 * Neither is an EVIDENCE TYPE. "Current listing", "Recent sales median" and
 * "Retail price" say what kind of number this is; they live in
 * @/lib/sourceEvidence, they are neutral, and they apply to contributing and
 * excluded values alike.
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
 * price. `source_price_range` is computed from every ADMISSIBLE value, and
 * under v2 the contributor filter could then remove one of them - so a
 * one-source index beside a two-endpoint range was correct, and this line is
 * what made it legible. Under v3 the two sets coincide and the caption does
 * not appear; it stays for a payload from an API that has not been redeployed
 * yet. */
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
