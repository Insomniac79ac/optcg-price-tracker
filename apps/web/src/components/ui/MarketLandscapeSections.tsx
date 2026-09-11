"use client";

import { formatJpy } from "@/lib/format";
import {
  distributionTotal,
  hasValue,
  peakBucketCount,
  type MarketOverview,
} from "@/lib/marketAnalytics";

/** The body of the current market landscape: four headline statistics, where
 * prices cluster, how complete the coverage behind them is, and one honest
 * blank where movement will eventually go.
 *
 * NOTHING IN THIS FILE COMPUTES A PRICE. Every number is read from the
 * overview response and rendered; none is summed, scaled into a percentage,
 * corrected or filled in. The only arithmetic below is a bar's WIDTH as a
 * fraction of the tallest bar, which is layout, not data - the count printed
 * beside each bar is always the server's own.
 *
 * "Unavailable" is a first-class answer here, not an error state. A null
 * median means nothing in scope is priced; a null decile means too few
 * constituents to describe a distribution; a null coverage percentage means
 * the scope is empty and 0/0 has no answer. Each of those is TRUE and worth
 * saying, and every one of them would become a lie the moment it was rendered
 * as ¥0 or 0%.
 */

const UNAVAILABLE = "Unavailable";

// --- A. Primary statistics --------------------------------------------------

/** The four numbers a collector opens this page for.
 *
 * Deliberately four, and deliberately not a row of dense mono tiles: this is
 * the collector surface, so the value leads at display weight with a quiet
 * caption under it, rather than the terminal-style stat grid the admin
 * screens use. The supporting line beneath a stat is where a source's
 * observed/usable distinction gets explained in words, because that is a
 * sentence, not a metric.
 */
export function MarketLandscapeStats({ overview }: { overview: MarketOverview }) {
  const { coverage, scope, current_price: price } = overview;
  const band =
    hasValue(price.p10_jpy) && hasValue(price.p90_jpy)
      ? `${formatJpy(price.p10_jpy)} – ${formatJpy(price.p90_jpy)}`
      : UNAVAILABLE;

  return (
    <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
      <Stat
        label="Priced prints"
        value={coverage.usable_priced_prints.toLocaleString()}
        hint={pricedPrintsHint(overview)}
      />
      <Stat
        label="Catalogue coverage"
        // Null when the scope holds no active prints at all. 0/0 is not 0%,
        // and a coverage figure for an empty scope would be inventing a
        // denominator.
        value={hasValue(coverage.coverage_pct) ? `${coverage.coverage_pct}%` : UNAVAILABLE}
        hint={`of ${scope.active_prints.toLocaleString()} active ${
          scope.active_prints === 1 ? "print" : "prints"
        } in scope`}
      />
      <Stat label="Median price" value={formatOrUnavailable(price.median_jpy)} />
      <Stat
        label="Price band"
        value={band}
        // The reason is the server's own, and it distinguishes "nothing is
        // priced" from "too few priced things to describe a spread" - which
        // look identical if you only look at the nulls.
        hint={band === UNAVAILABLE ? bandReason(price.unavailable_reason) : "10th to 90th percentile"}
      />
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string | null }) {
  return (
    <div className="panel px-3.5 py-3">
      <div className="text-xs font-medium text-text-muted">
        {label}
      </div>
      <div
        className={`tabular mt-1.5 font-display font-semibold leading-tight text-text-primary ${
          value === UNAVAILABLE ? "text-base text-text-muted" : "text-[22px]"
        }`}
      >
        {value}
      </div>
      {hint && <div className="mt-1 text-[11px] leading-snug text-text-muted">{hint}</div>}
    </div>
  );
}

function formatOrUnavailable(value: number | null): string {
  return hasValue(value) ? formatJpy(value) : UNAVAILABLE;
}

/** Why a price band has no answer, in a collector's words.
 *
 * Keyed on the server's own reason string with a null fallback, the same rule
 * `describeSourceEvidence` keeps: a reason this build has never heard of
 * produces no sentence rather than a guessed one. */
const BAND_REASON_COPY: Record<string, string> = {
  no_usable_prices: "nothing in this scope is priced yet",
  insufficient_constituents: "too few priced prints to describe a spread",
};

function bandReason(reason: string | null): string | null {
  if (!reason) return null;
  return BAND_REASON_COPY[reason] ?? null;
}

/** The supporting line under "Priced prints".
 *
 * For a source basis this is where observed-but-not-usable is explained, in a
 * sentence rather than a badge. It renders only when the server actually
 * reported an observed count that exceeds the usable one - both counts are
 * null for Market Index, and equal for a source with nothing excluded, and in
 * neither case is there anything to explain. */
function pricedPrintsHint(overview: MarketOverview): string | null {
  const { observed_prints: observed, usable_priced_prints: usable } = overview.coverage;
  if (!hasValue(observed) || observed <= usable) return null;
  return `${observed.toLocaleString()} observed on this source`;
}

// --- B. Price distribution --------------------------------------------------

/** Where prices currently cluster, as fixed collector-readable bands.
 *
 * The bands and their labels are the SERVER's - it returns every band on every
 * request, including the empty ones, so the shape of this chart means the same
 * thing between two sets and between this week and next. Nothing here bins,
 * rescales or drops a band: an empty ¥30,000+ row is information, and hiding
 * it would make "no expensive cards priced here" indistinguishable from "this
 * chart does not go that high".
 *
 * Horizontal bars, not vertical: the band labels are words of real length
 * ("¥10,000–29,999"), and horizontally they sit on one line at 390px instead
 * of being rotated or truncated. One neutral teal throughout - a price band is
 * not a gain or a loss, and red/green here would invent a judgement the data
 * does not carry.
 */
export function MarketPriceDistribution({ overview }: { overview: MarketOverview }) {
  const { distribution } = overview;
  const peak = peakBucketCount(distribution);
  const total = distributionTotal(distribution);

  if (distribution.length === 0) {
    return (
      <SectionShell title="Price distribution">
        <p className="text-sm text-text-muted">
          No price bands available for this view.
        </p>
      </SectionShell>
    );
  }

  if (total === 0) {
    return (
      <SectionShell title="Price distribution">
        <p className="text-sm text-text-muted">
          Nothing in this scope is priced yet, so there is no distribution to show.
        </p>
      </SectionShell>
    );
  }

  return (
    <SectionShell
      title="Price distribution"
      caption="How many prints fall in each price band."
    >
      <ul className="space-y-1.5">
        {distribution.map((bucket) => {
          // Layout only. The number a reader sees is always `bucket.count`.
          const width = peak > 0 ? (bucket.count / peak) * 100 : 0;
          return (
            <li key={bucket.label} className="flex items-center gap-2.5">
              <span className="w-[104px] shrink-0 text-right text-[11px] text-text-secondary sm:w-[124px] sm:text-xs">
                {bucket.label}
              </span>
              <span className="flex min-w-0 flex-1 items-center gap-2">
                <span
                  aria-hidden
                  className="h-3.5 min-w-px rounded-[2px] bg-accent-teal/70"
                  style={{ width: `${width}%` }}
                />
                <span className="tabular shrink-0 text-[11px] text-text-muted sm:text-xs">
                  {bucket.count.toLocaleString()}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
    </SectionShell>
  );
}

// --- C. Coverage and composition --------------------------------------------

/** How complete the numbers above are, and what they are made of.
 *
 * The two bases answer genuinely different questions, so this renders two
 * different things - but the branch is on `kind`, which the server sends, and
 * never on which platform it is:
 *
 *   Market Index   what the index COMBINED - how many prints one source
 *                  priced and how many two or more agreed on. Called
 *                  composition, never confidence: `source_count` counts
 *                  contributors, and calling that a confidence score would
 *                  invent a quality claim the resolver never made.
 *   a source       what the source REPORTED, split into the prices Atlas can
 *                  use and the readings it cannot. This is the one that
 *                  matters: a platform can carry a number for a print without
 *                  that number being a price.
 */
export function MarketCoverageComposition({ overview }: { overview: MarketOverview }) {
  const { coverage } = overview;

  // MARKET INDEX RENDERS NOTHING HERE ANY MORE.
  //
  // This branch used to show "What the index is made of" - every priced print
  // split by how many SOURCES contributed to its Market Index. It was accurate
  // and it is now removed, because /analytics gained a panel of the same name
  // that answers a different question, and the two could not share a page.
  //
  // The collision was not merely verbal. On 2026-09-07 this section printed
  // `9 / 296 / 305` while the Index Composition panel above printed a
  // constituent count of 296 out of 305 priced - the same three numbers, from
  // unrelated populations. This section split the CURRENT live-resolver
  // prints by source count; the panel above splits the ARCHIVED constituents
  // of the newest published index point by rarity. The 296s are not the same
  // 296: only one print is in both the multi-source set and the
  // non-constituent set. A reader had no way to tell those apart, and the
  // upper panel is the one that actually describes the index.
  //
  // The source-basis branch below is untouched: "What this source reports" is
  // about a platform's own coverage, collides with nothing, and is still the
  // only place a collector learns that a constrained listing is not a price.
  if (overview.kind === "market_index") return null;

  // A source basis. `observed_prints` is null only for Market Index, so
  // reaching here without it means the server declined to answer - which is
  // not the same as zero, and is left unsaid rather than guessed at.
  if (!hasValue(coverage.observed_prints) || coverage.observed_prints === 0) return null;

  const excluded = hasValue(coverage.excluded_constrained_prints)
    ? coverage.excluded_constrained_prints
    : 0;

  return (
    <SectionShell
      title="What this source reports"
      caption="Not every number a platform carries is a price a collector can pay."
      tone="supporting"
    >
      <SegmentedBar
        segments={[
          {
            key: "usable",
            label: "Usable prices",
            count: coverage.usable_priced_prints,
            className: "bg-accent-teal/80",
          },
          {
            key: "excluded",
            label: "Excluded by source constraints",
            count: excluded,
            className: "bg-accent-gold/45",
          },
        ]}
        total={coverage.observed_prints}
        totalLabel={`${coverage.observed_prints.toLocaleString()} prints observed on this source`}
      />
      {excluded > 0 && (
        // Stated plainly and without alarm. These prints are listed and have
        // history; what they lack is a CURRENT reading that means a market
        // price - a platform minimum is a floor the listing sits on, not what
        // the card is worth. The wording avoids implying either that the
        // cards are untracked or that the constrained figure is a price.
        <p className="mt-2.5 text-[11px] leading-relaxed text-text-muted">
          These prints are tracked and observed on this source. Their current reading is a
          platform constraint rather than a market price, so it is counted separately and
          never enters the median, the price band or the distribution above.
        </p>
      )}
    </SectionShell>
  );
}

interface Segment {
  key: string;
  label: string;
  count: number;
  className: string;
}

/** One bar split into named parts, with the parts also listed as text.
 *
 * The list is not redundant with the bar: it is the accessible reading of it,
 * and at 390px it is the only part that can carry an exact number. The bar
 * itself is aria-hidden for that reason. */
function SegmentedBar({
  segments,
  total,
  totalLabel,
}: {
  segments: Segment[];
  total: number;
  /** What the total IS, in the caller's words. Required rather than derived,
   * because the two bases' totals are different quantities: a source's total
   * is what it observed, and the index's is what it priced. One shared
   * sentence would have to be wrong for one of them. */
  totalLabel: string;
}) {
  return (
    <div>
      {total > 0 && (
        <div
          aria-hidden
          className="flex h-2.5 w-full overflow-hidden rounded-[3px] bg-bg-page"
        >
          {segments.map((segment) => (
            <span
              key={segment.key}
              className={segment.className}
              style={{ width: `${(segment.count / total) * 100}%` }}
            />
          ))}
        </div>
      )}
      <ul className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1.5">
        {segments.map((segment) => (
          <li key={segment.key} className="flex items-baseline gap-1.5 text-xs">
            <span aria-hidden className={`h-2 w-2 shrink-0 rounded-[2px] ${segment.className}`} />
            <span className="tabular font-medium text-text-primary">
              {segment.count.toLocaleString()}
            </span>
            <span className="text-text-muted">{segment.label}</span>
          </li>
        ))}
      </ul>
      <p className="mt-1.5 text-[11px] text-text-muted">{totalLabel}</p>
    </div>
  );
}

// --- D. Movement ------------------------------------------------------------

/** The deliberately empty section.
 *
 * There is no disabled chart here and no wall of 0.00%, because both would be
 * fabrications: rendering a movement control that answers nothing tells a
 * collector the answer is "no change" when the real answer is "not enough
 * history to say". Atlas archives one Market Index point per day, and until
 * that archive is long enough for two comparable points on the same print,
 * every change figure it could compute would be null.
 *
 * The section exists anyway so movement has somewhere to graduate into when
 * the history is real, without the page being redesigned around it. */
export function MarketMovementUnavailable() {
  return (
    <SectionShell title="Price movement" tone="supporting">
      <p className="text-sm text-text-secondary">Not enough comparable price history yet.</p>
      <p className="mt-1.5 max-w-prose text-[13px] leading-relaxed text-text-muted">
        Atlas records one price point per print per day. Movement analytics arrive once that
        archive is long enough to compare a card against its own past honestly — until then this
        page reports what prices are, not how they have changed.
      </p>
    </SectionShell>
  );
}

// --- shared shell -----------------------------------------------------------

/** `primary` is the answer a collector came for; `supporting` is how that
 * answer was arrived at.
 *
 * They deliberately do NOT look the same. Every section was a bordered
 * charcoal panel at first, which gave a methodology note about excluded
 * SNKRDUNK readings exactly the visual weight of the price distribution and
 * flattened the page into a stack of interchangeable dashboard widgets. A
 * supporting section now drops the box entirely and hangs off a hairline rule,
 * so the eye reaches the chart first and the explanation second - which is the
 * order they are actually read in. */
function SectionShell({
  title,
  caption,
  tone = "primary",
  children,
}: {
  title: string;
  caption?: string;
  tone?: "primary" | "supporting";
  children: React.ReactNode;
}) {
  const supporting = tone === "supporting";
  return (
    <section
      className={
        supporting ? "border-t border-border-muted px-1 pt-4" : "panel px-4 py-3.5"
      }
    >
      <h2
        className={
          supporting
            ? "font-display text-sm font-semibold text-text-secondary"
            : "font-display text-[15px] font-semibold text-text-primary"
        }
      >
        {title}
      </h2>
      {caption && (
        <p className={`text-[12px] text-text-muted ${supporting ? "mt-1.5" : "mt-0.5"}`}>
          {caption}
        </p>
      )}
      <div className="mt-3">{children}</div>
    </section>
  );
}
