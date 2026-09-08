"use client";

import { breadthShare, type IndexPoint } from "@/lib/cardPirateIndex";

/** How the index's constituents moved on the newest published day.
 *
 * NO REQUEST OF ITS OWN. Every figure here is already on the newest point of
 * the `IndexSeries` the hero above is drawing - `movers_up`, `movers_down`,
 * `movers_flat`, `constituent_count`, `eligible_print_count`, `capped_count`
 * are all published by `/analytics/index`. A `breadth` endpoint, or a second
 * index request, would create a second place for the same fact to be right.
 *
 * NOT RED AND GREEN. `docs/interface_design_system.md` reserves
 * `--signal-green`/`--signal-red` for the admin surface, and says
 * collector-facing price movement never gets a dominant red/green treatment.
 * The pairing used instead is the Atlas mark's own: gold north, teal south.
 * It is already the product's vocabulary for direction, it carries no
 * profit-and-loss connotation, and it survives the common colour-vision
 * deficiencies that red/green does not.
 */

const UP_COLOR = "var(--accent-gold)";
const DOWN_COLOR = "var(--accent-teal)";
const FLAT_COLOR = "var(--border-default)";

function Figure({
  value,
  label,
  color,
  testId,
}: {
  value: number;
  label: string;
  color: string;
  testId: string;
}) {
  return (
    <div className="min-w-0">
      <div className="flex items-baseline gap-1.5">
        <span
          aria-hidden="true"
          className="h-2 w-2 shrink-0 rounded-[2px]"
          style={{ backgroundColor: color }}
        />
        <span
          className="font-display text-[22px] font-semibold leading-none tracking-tight text-text-primary sm:text-[25px]"
          data-testid={testId}
        >
          {value}
        </span>
      </div>
      <span className="mono mt-1.5 block text-[10px] uppercase tracking-[0.14em] text-text-muted">
        {label}
      </span>
    </div>
  );
}

export function MarketBreadthPanel({ point }: { point: IndexPoint | null }) {
  const hasBreadth =
    point !== null &&
    point.movers_up !== null &&
    point.movers_down !== null &&
    point.movers_flat !== null;

  return (
    <section
      aria-labelledby="market-breadth-heading"
      data-testid="market-breadth"
      className="flex min-h-[268px] flex-col rounded-panel border border-border-muted bg-bg-surface p-4 sm:p-5"
    >
      <h3
        id="market-breadth-heading"
        className="font-display text-[16px] font-semibold leading-tight tracking-tight text-text-primary"
      >
        Market Breadth
      </h3>
      <p className="mt-1 text-[12px] leading-relaxed text-text-secondary">
        How today&rsquo;s Index constituents moved versus the prior point.
      </p>

      {!hasBreadth ? (
        // A base point carries NULL breadth by table constraint - it came from
        // no step, so there is no prior point to have moved against. Saying so
        // is the honest answer; three zeroes would claim a measurement.
        <p
          className="mt-6 text-[12px] leading-relaxed text-text-muted"
          data-testid="breadth-unavailable"
        >
          {point === null
            ? "Breadth is unavailable right now."
            : "This is the first published day of the index, so there is no prior point to compare against."}
        </p>
      ) : (
        <BreadthBody point={point} />
      )}
    </section>
  );
}

function BreadthBody({ point }: { point: IndexPoint }) {
  const up = point.movers_up ?? 0;
  const down = point.movers_down ?? 0;
  const flat = point.movers_flat ?? 0;
  const total = point.constituent_count;

  // DISPLAY GEOMETRY ONLY, and safe at zero: `breadthShare` returns 0 rather
  // than NaN for an empty constituent set, so the bar renders as absent
  // instead of as a broken element.
  const segments = [
    { key: "up", width: breadthShare(up, total), color: UP_COLOR },
    { key: "down", width: breadthShare(down, total), color: DOWN_COLOR },
    { key: "flat", width: breadthShare(flat, total), color: FLAT_COLOR },
  ];

  return (
    <>
      <div className="mt-5 grid grid-cols-3 gap-3">
        <Figure value={up} label="Up" color={UP_COLOR} testId="breadth-up" />
        <Figure value={down} label="Down" color={DOWN_COLOR} testId="breadth-down" />
        <Figure value={flat} label="Unchanged" color={FLAT_COLOR} testId="breadth-flat" />
      </div>

      {/* The bar is a picture of the three numbers above it, so it is
          `aria-hidden` and the sentence beside it carries the meaning. A
          `progressbar` role would be wrong: this is a composition of three
          parts, not one value on a scale. */}
      <div
        aria-hidden="true"
        data-testid="breadth-bar"
        className="mt-4 flex h-2 w-full overflow-hidden rounded-full bg-bg-elevated"
      >
        {segments.map((segment) => (
          <span
            key={segment.key}
            data-testid={`breadth-bar-${segment.key}`}
            style={{ width: `${segment.width}%`, backgroundColor: segment.color }}
          />
        ))}
      </div>
      <span className="sr-only" data-testid="breadth-summary">
        Of {total} constituents comparable with the prior index point, {up} moved
        up, {down} moved down and {flat} were unchanged.
      </span>

      <dl className="mt-5 space-y-1.5 border-t border-border-muted pt-4">
        {/* TWO COUNTS, NO EXPLANATION OF THE GAP. `eligible_print_count` is
            usually larger than `constituent_count`, and the reasons - entrants,
            version mismatches, contributor churn - are computed by the
            estimator and NOT persisted on the point. Naming any of them here
            would be the client inventing a cause the payload cannot support,
            so the two facts are stated and the difference is left unnarrated. */}
        <div className="flex items-baseline gap-2 text-[12px] leading-relaxed">
          <dt className="mono shrink-0 tabular-nums text-text-primary">
            {point.eligible_print_count}
          </dt>
          <dd className="text-text-secondary">priced today</dd>
        </div>
        <div className="flex items-baseline gap-2 text-[12px] leading-relaxed">
          <dt className="mono shrink-0 tabular-nums text-text-primary">{total}</dt>
          <dd className="text-text-secondary">comparable with the prior index point</dd>
        </div>
        {/* Omitted entirely at zero rather than printed as "0 capped". A
            capping line exists to disclose that the methodology limited some
            moves; on a day it limited none there is nothing to disclose, and
            the row would be noise the reader has to read to dismiss. */}
        {point.capped_count !== null && point.capped_count > 0 && (
          <div
            className="flex items-baseline gap-2 text-[12px] leading-relaxed"
            data-testid="breadth-capped"
          >
            <dt className="mono shrink-0 tabular-nums text-text-primary">
              {point.capped_count}
            </dt>
            <dd className="text-text-secondary">moves capped by index methodology</dd>
          </div>
        )}
      </dl>
    </>
  );
}
