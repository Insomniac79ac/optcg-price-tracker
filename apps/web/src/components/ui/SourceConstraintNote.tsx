import { describeSourceConstraint } from "@/lib/sourceConstraint";

/** The two fields this note reads, structurally shared by the card-keyed
 * `MarketIndexSourceValue` and the print-keyed `PrintMarketIndexSourceValue` -
 * so one component serves both detail surfaces without either importing the
 * other's type. */
export interface ConstrainedSourceValue {
  eligible: boolean;
  constraint?: string | null;
}

const TONE_CLASS = {
  // A documented platform limitation, not broken data - the same quiet
  // surface the panel itself uses, so it reads as a footnote, not an alert.
  informational: "border border-border-muted bg-bg-card/70 text-text-secondary",
  // Deliberately the exact amber already used by the "stale" marker: a mild
  // caution this product already has a vocabulary for, and no louder.
  caution: "bg-signal-warning/15 text-signal-warning",
} as const;

/** Why a visible source price may not mean what its number says, and whether
 * it counted toward the Market Index.
 *
 * Renders nothing at all for an ordinary eligible value, so an unconstrained
 * source panel is byte-identical to what it was before this component existed.
 *
 * Intended for `market_index.source_values` rows - the values that were
 * actually candidates for the index. Auxiliary values (e.g. Yuyu-Tei's dealer
 * buy price) are never candidates in the first place, so "not used in Market
 * Index" would be noise rather than news; no current surface renders them
 * through this component.
 *
 * Everything shown comes from the API's own `constraint` and `eligible`
 * fields. There is deliberately no client-side rule here: this component never
 * looks at `value_jpy`, never compares a source name, and never re-derives
 * eligibility - the backend already decided both, and a second opinion in the
 * browser is exactly how the two would drift apart.
 *
 * The raw price stays the loudest thing in the panel; this is 11px supporting
 * text underneath it. A constrained price is still a real, quotable number a
 * collector may want to see - it is explained here, never hidden or dimmed. */
export function SourceConstraintNote({ value }: { value: ConstrainedSourceValue }) {
  const copy = describeSourceConstraint(value.constraint);
  const showExclusion = !value.eligible && !copy?.statesExclusion;

  if (!copy && !showExclusion) return null;

  return (
    <div className="mt-2 border-t border-border-muted/70 pt-2">
      {copy && (
        <>
          <span
            className={`inline-flex max-w-full items-center rounded px-1.5 py-px text-[10px] font-medium leading-4 ${TONE_CLASS[copy.tone]}`}
          >
            {copy.label}
          </span>
          <p className="mt-1 text-[11px] leading-snug text-text-secondary">
            {copy.explanation}
          </p>
        </>
      )}
      {showExclusion && (
        <p className={`text-[11px] leading-snug text-text-faint ${copy ? "mt-1" : ""}`}>
          Not used in Market Index
        </p>
      )}
    </div>
  );
}
