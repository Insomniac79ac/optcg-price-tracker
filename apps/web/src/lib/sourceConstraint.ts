/** Collector-facing copy for a source value's `constraint`.
 *
 * The API's `constraint` (see services/api/app/services/source_semantics.py)
 * names *why a visible raw price may not mean what its number says*. Those
 * names - `platform_floor`, `below_platform_minimum` - are backend vocabulary
 * and must never reach a collector's eyes. This module is the one place that
 * turns one into a sentence, so the copy can be changed or translated without
 * touching either detail page.
 *
 * The copy is deliberately generic: it names no source and quotes no
 * threshold. Those are the backend's facts, and a sentence here saying which
 * platform has which minimum would be a second, silently-drifting copy of a
 * rule this app does not own - stale the moment the backend's rule changes,
 * and wrong for every other source that later gets a minimum of its own. What
 * this module knows is the *shape* of each semantic state ("at the source's
 * minimum", "below the source's minimum"); the source's identity is already
 * on screen beside the price, from the API's own data.
 */

/** Which existing visual vocabulary a constraint borrows.
 *
 * `informational` is a known, documented platform limitation - real data,
 * behaving exactly as the platform says it will, so it gets a quiet neutral
 * treatment rather than anything that reads as an error. `caution` is data
 * that contradicts its own source's rules, which is worth the same mild
 * amber the "stale" marker already uses - and no more than that. */
export type SourceConstraintTone = "informational" | "caution";

export interface SourceConstraintCopy {
  /** Short human label, e.g. shown as a chip beside the price. */
  label: string;
  /** One plain sentence a collector can act on. */
  explanation: string;
  tone: SourceConstraintTone;
  /** True when `explanation` already tells the reader this value is not in the
   * Market Index, so a caller's generic "Not used in Market Index" line would
   * only repeat it. */
  statesExclusion: boolean;
}

const SOURCE_CONSTRAINT_COPY: Record<string, SourceConstraintCopy> = {
  platform_floor: {
    label: "Minimum listing price",
    explanation:
      "This value is at the source's minimum listing price and may not reflect the card's actual market price.",
    tone: "informational",
    statesExclusion: false,
  },
  below_platform_minimum: {
    label: "Source data anomaly",
    explanation:
      "This price is below the source's known minimum and is not used in Market Index.",
    tone: "caution",
    statesExclusion: true,
  },
};

/** The copy for one `constraint`, or null when there is nothing to say.
 *
 * Null covers three different situations on purpose, because the honest UI
 * response to all three is identical - show the price, add no badge:
 *   - `null`/`undefined`: the backend says this value is unconstrained, or is
 *     an older API that predates the field entirely.
 *   - an empty string.
 *   - a constraint name this build has never heard of. A future backend
 *     release may add one; rendering its raw identifier would leak internal
 *     vocabulary, and inventing a label like "Source constraint" would state
 *     something about the price that this build genuinely does not know. The
 *     row still reports that it is not counted toward the index, which comes
 *     from `eligible` and is true whatever the constraint turns out to mean.
 */
export function describeSourceConstraint(
  constraint: string | null | undefined,
): SourceConstraintCopy | null {
  if (!constraint) return null;
  return SOURCE_CONSTRAINT_COPY[constraint] ?? null;
}
