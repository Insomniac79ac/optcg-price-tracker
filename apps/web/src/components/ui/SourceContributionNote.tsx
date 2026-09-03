import { sourceConstraintStatesExclusion } from "@/lib/sourceConstraint";
import {
  isReferenceOnly,
  REFERENCE_ONLY_EXPLANATION,
  REFERENCE_ONLY_LABEL,
} from "@/lib/sourceContribution";

/** "Reference only" - a real, current, trustworthy price that nevertheless
 * did not feed Market Index.
 *
 * Deliberately a separate component from SourceConstraintNote rather than a
 * fourth entry in its vocabulary, and a third thing again from the neutral
 * evidence-type label above it. A constraint says why a number may not mean
 * what it says; this says nothing is wrong with the number at all, only that
 * the index was computed from something else. Folding the two together would
 * have made "stood aside under the v2 role rules" read as a data problem.
 *
 * Nothing is re-derived. `contributes_to_index` arrives decided by
 * app.services.market_index, and this component neither consults `eligible`
 * to guess it, nor compares the price to the index, nor knows which source is
 * capable of being a fallback.
 *
 * Silent when the constraint layer has already said this value is out of the
 * index - an ineligible platform-minimum price keeps its own, more specific
 * explanation instead of gaining a second badge that says less.
 *
 * That silence is now the ordinary case rather than the exception. A Market
 * Index v3 backend excludes a value only by finding it INELIGIBLE, and
 * sourceConstraintStatesExclusion is true of every ineligible value - so
 * against a v3 API this component renders nothing at all, and the chip appears
 * only for a payload from an API still applying v2's role filter. That is the
 * intended outcome rather than a regression: v3 stopped excluding eligible
 * asking prices, so there is no longer an eligible price to explain away. What
 * a collector reads instead is the neutral evidence-type label from
 * @/lib/sourceEvidence - "Current listing" - which says what the price is
 * rather than what it failed to be.
 *
 * Neutral by construction: the same quiet chip the `informational` constraint
 * tone uses, 11px supporting text, no amber, no warning. The raw price above
 * stays the loudest thing in the panel. */
export interface ContributingSourceValue {
  eligible: boolean;
  constraint?: string | null;
  contributes_to_index?: boolean | null;
}

export function SourceContributionNote({ value }: { value: ContributingSourceValue }) {
  if (!isReferenceOnly(value)) return null;
  if (sourceConstraintStatesExclusion(value)) return null;

  return (
    <div className="mt-2 border-t border-border-muted/70 pt-2">
      <span className="inline-flex max-w-full items-center rounded border border-border-muted bg-bg-card/70 px-1.5 py-px text-[10px] font-medium leading-4 text-text-secondary">
        {REFERENCE_ONLY_LABEL}
      </span>
      <p className="mt-1 text-[11px] leading-snug text-text-secondary">
        {REFERENCE_ONLY_EXPLANATION}
      </p>
    </div>
  );
}
