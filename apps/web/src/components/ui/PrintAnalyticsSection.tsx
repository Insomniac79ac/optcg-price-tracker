"use client";

import { PrintSeriesChartPanel } from "@/components/ui/PrintPriceHistory";
import { WindowTokenControl } from "@/components/ui/WindowTokenControl";
import { formatDate, formatJpy } from "@/lib/format";
import {
  changeUnavailableCopy,
  coverageQualifier,
  windowShortfall,
  type PrintAnalytics,
  type PrintAnalyticsChange,
  type PrintAnalyticsHeadline,
} from "@/lib/printAnalytics";

/** One exact print's historical analytics band: the archived Market Index
 * headline, the multi-series chart, and the timeframe control.
 *
 * EVERY FIGURE HERE IS ARCHIVED, AND EVERY FIGURE HERE IS THE SERVER'S. The
 * headline is read field-by-field off `analytics.headline`; nothing in this
 * file derives a current value, a starting value, a high, a low, a change or a
 * day count from the chart's points. That is not a style preference: the
 * points on the plot are a *window* of archived days, and a maximum taken
 * across them in a browser would disagree with the server the moment a day
 * carried a null value, spanned a methodology break, or fell outside the
 * window the server actually measured.
 *
 * IT IS ARCHIVED, NOT LIVE, AND THE PAGE SAYS SO. `current_value_jpy` is the
 * newest value Atlas WROTE DOWN, stamped with `current_as_of`, and it is the
 * number the chart, the starting value, the high, the low, the change and the
 * observed-day count all reconcile against. The live index - resolved at
 * request time on `GET /prints/{id}` - is a different number that can
 * legitimately differ, and it renders in the live-market section below under
 * its own label. Neither is allowed to stand on this page unqualified.
 *
 * `As of <date>` IS PROVENANCE, NOT FRESHNESS. It says which archived day
 * this figure is, in the same way a chart point has a date. It is deliberately
 * not "updated N hours ago", not a staleness badge and not a warning: the
 * archive is written once a day by design, so its age is the design rather
 * than a fault to flag.
 */
export function PrintAnalyticsSection({
  analytics,
  pressed,
  loading,
  onWindowChange,
}: {
  /** The most recent successful response, or null before the first lands.
   * Kept on screen while the next window is in flight - see `loading`. */
  analytics: PrintAnalytics | null;
  /** The token the control shows as pressed: the server's own echo. */
  pressed: string;
  loading: boolean;
  onWindowChange: (window: string) => void;
}) {
  const headline = analytics?.headline ?? null;

  return (
    <section className="mt-7 border-t border-border-muted pt-5" data-testid="print-analytics">
      <h2 className="mono text-[10px] font-medium uppercase leading-none tracking-[0.16em] text-text-muted">
        Market Index
      </h2>

      {headline ? (
        <AnalyticsHeadline headline={headline} />
      ) : (
        // Reserves the headline's room from the first frame so the chart and
        // everything below it do not jump when the response lands.
        <div className="mt-2 h-[92px]" aria-hidden="true" />
      )}

      <PrintSeriesChartPanel
        series={analytics}
        loading={loading}
        // THE DOMINANT ANALYTICAL ELEMENT. Roughly double the 168px this chart
        // occupied as a footnote under the source panels, and taller than the
        // headline above it - so the shape of the history, not the single
        // number, is what a reader takes from this band. Mobile keeps a real
        // plot rather than a strip: 300px is enough for the y-axis to carry
        // three labelled gridlines at 10px type without collapsing.
        chartHeightClass="h-[300px] sm:h-[340px] lg:h-[380px]"
      />

      <div className="mt-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <WindowTokenControl
          window={pressed}
          windows={analytics?.windows ?? []}
          onChange={onWindowChange}
          shortfallFor={windowShortfall}
          label="Analytics window"
          testId="print-analytics-window"
        />
        {/* The one thing the control cannot say about itself: that a greyed
            token is a statement about THIS PRINT's recorded history, not about
            Atlas being broken or the button being unimplemented. */}
        {analytics?.windows.some((row) => !row.available) && (
          <p className="text-[10px] leading-snug text-text-faint">
            Dimmed spans reach further back than this print&rsquo;s recorded history.
          </p>
        )}
      </div>
    </section>
  );
}

/** The archived headline: the value, the day it is, its movement, and the four
 * figures that describe the window around it.
 *
 * WHY THE FOUR ARE A ROW AND NOT FOUR CARDS. Four bordered stat tiles is the
 * generic analytics-product gesture the visual rubric names outright, and it
 * would also lie about weight: these are context for the gold figure and the
 * chart, not four peers of it. A single quiet row keeps the band's centre on
 * the value and the plot.
 *
 * Each figure carries its own date where the server publishes one. That is not
 * decoration - "high ¥27,400" and "high ¥27,400 on Aug 21" are different
 * claims, and the second is the one that lets a reader find the point on the
 * chart directly below.
 */
function AnalyticsHeadline({ headline }: { headline: PrintAnalyticsHeadline }) {
  // A print with no archived index has no headline to render. Never ¥0, and
  // never a dash standing where a price belongs - see the same rule in
  // MarketIndexValue and app.services.market_index.
  if (headline.current_value_jpy === null) {
    return (
      <div className="mt-2">
        <p className="mono tabular text-2xl font-semibold price-muted">Index unavailable</p>
        <p className="mt-1.5 text-[11px] leading-snug text-text-secondary">
          Atlas has not archived a Market Index for this print yet.
        </p>
      </div>
    );
  }

  const coverage = coverageQualifier(headline.coverage_status);

  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span
          className="mono tabular text-[30px] font-semibold leading-none text-accent-gold sm:text-4xl"
          data-testid="print-analytics-current"
        >
          {formatJpy(headline.current_value_jpy)}
        </span>
        {headline.current_as_of && (
          <span className="text-[11px] text-text-faint">
            As of {formatDate(headline.current_as_of)}
          </span>
        )}
      </div>

      <ChangeLine headline={headline} />

      {coverage && (
        <p className="mt-1.5 text-[11px] leading-snug text-text-secondary">{coverage}</p>
      )}

      <dl
        className="mt-3 flex flex-wrap gap-x-6 gap-y-2"
        data-testid="print-analytics-stats"
      >
        <Stat
          label="Starting"
          value={headline.starting_value_jpy}
          asOf={headline.starting_as_of}
        />
        <Stat label="High" value={headline.high_value_jpy} asOf={headline.high_as_of} />
        <Stat label="Low" value={headline.low_value_jpy} asOf={headline.low_as_of} />
        <ObservedDays days={headline.observed_days} />
      </dl>
    </div>
  );
}

/** One archived figure and the day it belongs to. */
function Stat({
  label,
  value,
  asOf,
}: {
  label: string;
  value: number | null;
  asOf: string | null;
}) {
  return (
    <div>
      <dt className="mono text-[9px] uppercase leading-none tracking-[0.14em] text-text-faint">
        {label}
      </dt>
      <dd className="mono tabular mt-1 text-sm font-medium text-text-primary">
        {value === null ? <span className="price-muted">—</span> : formatJpy(value)}
        {value !== null && asOf && (
          <span className="ml-1.5 text-[10px] font-normal text-text-faint">
            {formatDate(asOf)}
          </span>
        )}
      </dd>
    </div>
  );
}

/** How many days the window actually holds a usable archived index for.
 *
 * DISTINCT ARCHIVED DAYS - NOT SALES, TRADES, VOLUME, LISTINGS OR A SAMPLE
 * SIZE. No such figure exists anywhere in Atlas, and the wording here stays
 * "observed" precisely so it cannot be read as one: it counts days Atlas
 * recorded a number, and says nothing whatever about how often the card
 * changed hands.
 */
function ObservedDays({ days }: { days: number }) {
  return (
    <div>
      <dt className="mono text-[9px] uppercase leading-none tracking-[0.14em] text-text-faint">
        Observed
      </dt>
      <dd className="mono tabular mt-1 text-sm font-medium text-text-primary">
        {days}
        <span className="ml-1.5 text-[10px] font-normal text-text-faint">
          {days === 1 ? "day" : "days"}
        </span>
      </dd>
    </div>
  );
}

/** The window's movement, or the server's reason there isn't one.
 *
 * NEVER COMPUTED HERE, AND NEVER IN RED OR GREEN. The server publishes a
 * change only where the two ends of the window are genuinely comparable - it
 * refuses across an index-version bump, a source-semantics bump, or a change
 * in which sources built the number - so a first-vs-last subtraction in the
 * browser would confidently report a methodology change as a price movement.
 * When it refuses, the refusal is the content: the reason is why a chart with
 * a visible slope can honestly report no movement.
 *
 * The direction is carried by the sign, in the collector palette. A red/green
 * delta is the trading-terminal vocabulary this product reserves for the
 * admin surface (docs/brand.md "Colour rules"), and a card that lost value is
 * not an alarm.
 */
function ChangeLine({ headline }: { headline: PrintAnalyticsHeadline }) {
  if (headline.change) return <PublishedChange change={headline.change} />;

  const reason = changeUnavailableCopy(headline.change_unavailable_reason);
  return (
    <p
      className="mt-2 text-[11px] leading-snug text-text-muted"
      data-testid="print-analytics-change-unavailable"
    >
      {/* An unrecognised reason gets the neutral sentence rather than a
          guessed one: the server may name a refusal this build has never
          heard of, and inventing prose for it would assert a meaning we do
          not have. */}
      {reason ?? "No comparable change to report for this window."}
    </p>
  );
}

function PublishedChange({ change }: { change: PrintAnalyticsChange }) {
  const rising = change.absolute_jpy > 0;
  const flat = change.absolute_jpy === 0;
  const sign = rising ? "+" : flat ? "" : "−";
  const absolute = formatJpy(Math.abs(change.absolute_jpy));
  const pct = Math.abs(change.pct).toFixed(2);

  return (
    <p
      className="mono tabular mt-2 text-[13px] leading-snug text-text-primary"
      data-testid="print-analytics-change"
    >
      <span>
        {sign}
        {absolute}
      </span>
      <span className="ml-2 text-text-secondary">
        ({sign}
        {pct}%)
      </span>
      <span className="mono ml-2 text-[10px] font-normal text-text-faint">
        {formatDate(change.from_date)} → {formatDate(change.to_date)}
      </span>
      {/* The window still crosses a methodology boundary; the ENDS were
          comparable, which is a narrower claim than "nothing changed in
          between". Saying so is what keeps this figure from being read as a
          clean like-for-like across the whole span. */}
      {change.spans_break && (
        <span className="ml-2 block text-[10px] font-normal text-text-muted sm:ml-0 sm:mt-1">
          Atlas changed how this was measured inside the window; the two ends are still
          comparable.
        </span>
      )}
    </p>
  );
}
