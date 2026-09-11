"use client";

import {
  formatIndexDay,
  type IndexComposition,
  type IndexRarityBucket,
} from "@/lib/cardPirateIndex";

/** What the Card Pirate Index is made of, by rarity.
 *
 * EVERY NUMBER HERE IS THE SERVER'S. `count` and `pct` are rendered exactly as
 * `/analytics/index/composition` sent them; nothing in this file divides,
 * accumulates or re-derives a share, and nothing reconstructs who was a
 * constituent. That is not squeamishness: constituency is a pairwise property
 * of two archived snapshot days, so a client that tried would need the archive
 * and the estimator, and would produce a chart free to disagree with the
 * `constituent_count` printed in the middle of it.
 *
 * IT DOES NOT MOVE WITH THE TIMEFRAME. The composition describes the newest
 * published point, which is the same point whether the chart above shows two
 * weeks or everything. The panel takes no window prop, so pressing 1Y cannot
 * reach it.
 */

/** The slice palette, drawn from the frozen token set rather than invented.
 *
 * Six brand hues in a fixed order, so the same rarity gets the same colour on
 * every render and between reloads. Distinguishable by LIGHTNESS as well as
 * hue, because the two teals and the two golds sit at different values - but
 * colour is never the only channel here: section 12.2's accessibility rule and
 * this panel's own legend mean every slice is named in text with its count and
 * share beside it. The donut is the shape of the answer; the legend IS the
 * answer.
 *
 * UNKNOWN is pinned to the faint neutral whatever its size. It is an absence
 * of catalogue metadata, not a rarity, and giving it a brand hue would let it
 * read as one. */
const SLICE_COLORS = [
  "var(--accent-gold)",
  "var(--parchment)",
  "var(--accent-teal)",
  "var(--accent-gold-hover)",
  "var(--accent-coral)",
  "var(--accent-teal-hover)",
] as const;

const UNKNOWN_KEY = "UNKNOWN";
const UNKNOWN_COLOR = "var(--text-faint)";

export function sliceColor(bucket: IndexRarityBucket, index: number): string {
  if (bucket.key === UNKNOWN_KEY) return UNKNOWN_COLOR;
  return SLICE_COLORS[index % SLICE_COLORS.length];
}

/** Geometry only. r is fixed so the arc maths stays integer-friendly. */
const R = 54;
const CIRCUMFERENCE = 2 * Math.PI * R;
const STROKE = 18;

/** A donut drawn as stroked arcs on one circle.
 *
 * Hand-rolled rather than charted. The page already carries Recharts for the
 * index line, but its ResponsiveContainer measures zero in jsdom - so a
 * charted donut would be untestable exactly where the honesty rules need
 * asserting, and would drag a measurement lifecycle into a figure whose size
 * never changes. `stroke-dasharray` on a fixed circle is the whole
 * implementation.
 *
 * `aria-hidden` because it is a picture OF the legend beside it. A screen
 * reader that walked seven unlabelled paths would hear geometry; the table
 * of labels, counts and shares says the same thing properly, and the panel's
 * own summary says it in one sentence.
 */
function Donut({ buckets, total }: { buckets: IndexRarityBucket[]; total: number }) {
  // Arc lengths and their running start, computed BEFORE the JSX rather than
  // accumulated inside the map. A `let` mutated during render is exactly what
  // the React compiler's immutability rule forbids, and it would also make the
  // ring depend on evaluation order.
  //
  // Geometry from the COUNTS, not from the server's rounded `pct`: two-place
  // percentages leave a residue that would show as a visible wedge of bare
  // track, while the counts close the circle exactly. The printed share stays
  // the server's - see the legend.
  const arcs = buckets.reduce<{ length: number; start: number }[]>((acc, bucket) => {
    const share = total > 0 ? bucket.count / total : 0;
    const previous = acc[acc.length - 1];
    const start = previous ? previous.start + previous.length : 0;
    acc.push({ length: share * CIRCUMFERENCE, start });
    return acc;
  }, []);

  return (
    <svg
      viewBox="0 0 140 140"
      className="h-[132px] w-[132px] shrink-0 sm:h-[148px] sm:w-[148px]"
      aria-hidden="true"
      data-testid="composition-donut"
    >
      {/* The track. Without it a rounding residue would show as a notch of
          page background rather than as a hairline of the panel's own
          surface. */}
      <circle
        cx="70"
        cy="70"
        r={R}
        fill="none"
        stroke="var(--border-muted)"
        strokeWidth={STROKE}
      />
      {buckets.map((bucket, i) => {
        const { length, start } = arcs[i];
        const dash = `${length} ${CIRCUMFERENCE - length}`;
        const rotation = (start / CIRCUMFERENCE) * 360 - 90;
        return (
          <circle
            key={bucket.key}
            cx="70"
            cy="70"
            r={R}
            fill="none"
            stroke={sliceColor(bucket, i)}
            strokeWidth={STROKE}
            strokeDasharray={dash}
            transform={`rotate(${rotation} 70 70)`}
          />
        );
      })}
    </svg>
  );
}

function Legend({ buckets, total }: { buckets: IndexRarityBucket[]; total: number }) {
  return (
    <dl className="min-w-0 flex-1 space-y-1" data-testid="composition-legend">
      {buckets.map((bucket, i) => (
        <div key={bucket.key} className="flex items-baseline gap-2">
          <span
            aria-hidden="true"
            className="mt-[1px] h-2 w-2 shrink-0 rounded-[2px]"
            style={{ backgroundColor: sliceColor(bucket, i) }}
          />
          <dt className="min-w-0 flex-1 truncate text-[12px] leading-relaxed text-text-secondary">
            {bucket.label}
          </dt>
          <dd className="mono shrink-0 text-[12px] tabular-nums text-text-primary">
            {bucket.count}
          </dd>
          {/* The SERVER's percentage, verbatim. The column may total 99.99 or
              100.01, and that is correct: nudging a bucket to force 100 would
              print a share that disagrees with the count beside it. */}
          <dd className="mono w-[52px] shrink-0 text-right text-[12px] tabular-nums text-text-muted">
            {bucket.pct}%
          </dd>
        </div>
      ))}
      <span className="sr-only" data-testid="composition-summary">
        {total} constituents:{" "}
        {buckets.map((b) => `${b.label} ${b.count} (${b.pct}%)`).join(", ")}.
      </span>
    </dl>
  );
}

export function IndexCompositionPanel({
  composition,
  status,
}: {
  composition: IndexComposition | null;
  status: "loading" | "ready" | "error";
}) {
  return (
    <section
      aria-labelledby="index-composition-heading"
      data-testid="index-composition"
      // `min-h` reserves the panel's real height from the first frame, so the
      // section below does not jump when the response lands.
      className="flex min-h-[268px] flex-col rounded-panel border border-border-muted bg-bg-surface p-4 sm:p-5"
    >
      <h3
        id="index-composition-heading"
        className="font-display text-[16px] font-semibold leading-tight tracking-tight text-text-primary"
      >
        What’s in the index
      </h3>
      <p className="mt-1 text-[12px] leading-relaxed text-text-secondary">
        Cards in the index, by rarity.
      </p>

      {status === "error" || (status === "ready" && !Array.isArray(composition?.rarity)) ? (
        // QUIET, AND PANEL-LOCAL. The breadth panel beside this one is built
        // from the index series and is unaffected, so a composition failure
        // must not take the row - let alone the page - down with it.
        <p
          className="mt-6 text-[12px] leading-relaxed text-text-muted"
          data-testid="composition-unavailable"
        >
          Composition is unavailable right now.
        </p>
      ) : status === "loading" || composition === null ? (
        <div className="mt-5 flex items-center gap-4" aria-busy="true">
          <span className="sr-only">Loading the index composition…</span>
          <div className="h-[132px] w-[132px] shrink-0 rounded-full bg-bg-elevated sm:h-[148px] sm:w-[148px]" />
          <div className="flex-1 space-y-2">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="h-3 w-full rounded bg-bg-elevated" />
            ))}
          </div>
        </div>
      ) : composition.rarity.length === 0 ? (
        // An honest empty state rather than an empty ring. A base point opens
        // a segment and has no constituents at all; drawing a hollow donut
        // over "0" would suggest a chart that failed rather than a day that
        // genuinely had nothing to compare.
        <p
          className="mt-6 text-[12px] leading-relaxed text-text-muted"
          data-testid="composition-empty"
        >
          This is the first published day of the index, so there is nothing yet
          to compare it against and no composition to show.
        </p>
      ) : (
        <div className="mt-5 flex items-center gap-4 sm:gap-5">
          <div className="relative shrink-0">
            <Donut buckets={composition.rarity} total={composition.constituent_count} />
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <span
                className="font-display text-[24px] font-semibold leading-none tracking-tight text-text-primary sm:text-[27px]"
                data-testid="composition-count"
              >
                {composition.constituent_count}
              </span>
              <span className="mt-1 text-[11px] text-text-muted">
                constituents
              </span>
            </div>
          </div>
          <Legend buckets={composition.rarity} total={composition.constituent_count} />
        </div>
      )}

      {composition && status === "ready" && (
        <p
          className="mt-auto pt-4 text-[11px] leading-relaxed text-text-faint"
          data-testid="composition-meta"
        >
          As of {formatIndexDay(composition.as_of)}. Rarity uses current
          catalogue classification.
        </p>
      )}
    </section>
  );
}
