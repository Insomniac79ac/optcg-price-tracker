"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, XAxis, YAxis } from "recharts";

import { formatDate, formatJpy } from "@/lib/format";
import {
  buildChartRows,
  segmentDataKey,
  type PriceHistorySeriesView,
  type PriceHistoryView,
} from "@/lib/printPriceHistory";
import { SNKRDUNK, YUYUTEI } from "@/lib/prints";
import { describeSourceConstraint } from "@/lib/sourceConstraint";

/** Supporting evidence beneath the Market Index - never the centre of the page.
 *
 * Everything here is 11-13px metadata on the page's own surfaces, the chart is
 * 148px tall, and no value in this section is rendered in the gold the Market
 * Index owns. A collector arriving at a print should still read artwork,
 * identity, then index; this answers "and how has that moved?" for the reader
 * who goes looking, without competing for the first glance.
 *
 * There is no candlestick, no volume, no range band, no red/green movement
 * treatment and no interpolation across a gap. A decline is drawn in the same
 * stroke as a rise, because a collector looking at a card they own is not a
 * position holder being warned.
 */

/** One quiet stroke per source. Teal is this product's "trusted information"
 * accent and parchment its neutral ink; gold is deliberately absent, because
 * gold belongs to the Market Index value above and a history line borrowing it
 * would read as a second index. An unmapped source gets muted text colour
 * rather than a generated hue. */
const SERIES_COLOR: Record<string, string> = {
  [YUYUTEI]: "var(--accent-teal)",
  [SNKRDUNK]: "var(--parchment)",
};

function seriesColor(source: string): string {
  return SERIES_COLOR[source] ?? "var(--text-muted)";
}

/** Whether this print's history has arrived yet.
 *
 * The print itself and its history are two requests, and the page shows the
 * card as soon as the first lands rather than holding the hero back for
 * supporting evidence. That makes the section's arrival a layout event, which
 * is what `loading` exists to absorb - see PrintPriceHistorySection. */
export type PriceHistoryStatus = "loading" | "ready" | "unavailable";

/** The section, including the space it occupies before it has anything to say.
 *
 * WHY A PLACEHOLDER AND NOT JUST `null`. History is fetched separately from
 * the print, so rendering nothing until it resolves would drop a heading, a
 * 148px chart and two rows into the middle of the page a moment after the card
 * appears, shoving "About this print" and "Other printings" down under the
 * reader's eyes. The placeholder holds approximately the room the real section
 * takes, so the page settles once rather than twice.
 *
 * It is deliberately mute - a heading and two empty surfaces, no shimmer, no
 * spinner, no invented number. It claims that something is coming, which is
 * true, and nothing about what.
 *
 * `unavailable` renders nothing at all: a print no source has ever priced, or
 * a history request that failed, is a page without this section rather than a
 * page with an apology in it.
 */
export function PrintPriceHistorySection({
  status,
  view,
}: {
  status: PriceHistoryStatus;
  view: PriceHistoryView | null;
}) {
  if (status === "loading") return <PriceHistoryPlaceholder />;
  if (status === "unavailable" || !view) return null;
  return <PrintPriceHistory view={view} />;
}

function PriceHistoryPlaceholder() {
  return (
    <section className="mt-7 border-t border-border-muted pt-5" aria-hidden="true">
      <h2 className="mono text-[10px] font-medium uppercase leading-none tracking-[0.16em] text-text-muted">
        Price history
      </h2>
      <div className="mt-2.5 h-[148px] rounded-panel border border-border-muted/60 bg-bg-elevated/30" />
      <div className="mt-3 grid gap-2.5">
        <div className="h-[58px] rounded-panel border border-border-muted/60 bg-bg-elevated/30" />
        <div className="h-[58px] rounded-panel border border-border-muted/60 bg-bg-elevated/30" />
      </div>
    </section>
  );
}

export function PrintPriceHistory({ view }: { view: PriceHistoryView }) {
  // A source that never reported is not a fact about this card, so an empty
  // view renders no section at all rather than an empty-state box.
  if (view.series.length === 0) return null;

  const plotted = view.series.filter((entry) => entry.mode === "plotted");
  const rows = buildChartRows(view.series);

  return (
    <section className="mt-7 border-t border-border-muted pt-5">
      <h2 className="mono text-[10px] font-medium uppercase leading-none tracking-[0.16em] text-text-muted">
        Price history
      </h2>

      {view.hasChart && (
        <>
          <PriceHistoryLegend series={plotted} />
          <PriceHistoryChart series={plotted} rows={rows} />
        </>
      )}

      <div className="mt-3 grid gap-2.5">
        {view.series.map((entry) => (
          <SeriesRow key={entry.key} series={entry} />
        ))}
      </div>
    </section>
  );
}

/** Which stroke is which source. A short inline key rather than Recharts'
 * own legend, so it keeps the page's type scale and sits above the plot
 * instead of stealing height inside it. */
function PriceHistoryLegend({ series }: { series: PriceHistorySeriesView[] }) {
  return (
    <ul className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {series.map((entry) => (
        <li key={entry.key} className="flex items-center gap-1.5 text-[11px] text-text-secondary">
          <span
            aria-hidden="true"
            className="inline-block h-px w-4 rounded"
            style={{ backgroundColor: seriesColor(entry.source), boxShadow: "0 0 0 0.5px currentColor" }}
          />
          {entry.label}
        </li>
      ))}
    </ul>
  );
}

/** The plot itself: one line per SEGMENT, not per series.
 *
 * That is the whole mechanism behind "never draw through a constrained
 * observation". A series interrupted by a disqualified reading arrives here as
 * two segments, which are two separate <Line>s with two separate dataKeys, so
 * there is no path between them to stroke. `connectNulls` is on because within
 * one segment a null is merely the *other* source's timestamp, which this
 * series genuinely continued across.
 *
 * Animation is off outright rather than gated on a media query: this is a
 * static evidence chart, and a line that draws itself on every mount is motion
 * with nothing to say.
 */
function PriceHistoryChart({
  series,
  rows,
}: {
  series: PriceHistorySeriesView[];
  rows: ReturnType<typeof buildChartRows>;
}) {
  return (
    <div className="mt-2 h-[148px] w-full" data-testid="price-history-chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--border-muted)" vertical={false} />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(value: number) => formatDate(new Date(value).toISOString())}
            tick={{ fill: "var(--text-faint)", fontSize: 10 }}
            axisLine={{ stroke: "var(--border-muted)" }}
            tickLine={false}
            minTickGap={28}
          />
          <YAxis
            width={54}
            tickFormatter={(value: number) => formatJpy(value)}
            tick={{ fill: "var(--text-faint)", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            // A little headroom either side rather than a tight fit. On a
            // series that never moved, a fitted axis lands on ¥218-¥222 around
            // a flat ¥220 line and invites the reader to see one-yen movement
            // that is not there; padding the domain keeps a flat price looking
            // flat. It changes the axis only - no point's value is altered.
            domain={[
              (min: number) => Math.floor(min * 0.95),
              (max: number) => Math.ceil(max * 1.05),
            ]}
          />
          {series.flatMap((entry) =>
            entry.segments.map((_, index) => (
              <Line
                key={segmentDataKey(entry.key, index)}
                type="monotone"
                dataKey={segmentDataKey(entry.key, index)}
                stroke={seriesColor(entry.source)}
                strokeWidth={1.5}
                dot={false}
                activeDot={false}
                connectNulls
                isAnimationActive={false}
              />
            )),
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** One line of plain evidence per source series.
 *
 * The three modes are three different honest sentences, not three styles of
 * the same one - see lib/printPriceHistory for which a series earns.
 */
function SeriesRow({ series }: { series: PriceHistorySeriesView }) {
  if (series.mode === "constrained") return <ConstrainedSeriesRow series={series} />;

  return (
    <div className="rounded-panel border border-border-muted bg-bg-elevated/50 px-3 py-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="flex items-center gap-1.5 text-[11px] text-text-secondary">
          <span
            aria-hidden="true"
            className="inline-block h-px w-3.5"
            style={{ backgroundColor: seriesColor(series.source) }}
          />
          {series.label}
        </span>
        <span className="mono tabular text-sm font-medium text-text-primary">
          {formatJpy(series.latest?.priceJpy ?? null)}
        </span>
      </div>

      {series.mode === "compact" ? (
        <p className="mt-1 text-[11px] leading-snug text-text-faint">
          Seen {formatDate(series.latest?.observedAt ?? null)} · More history needed for a trend
        </p>
      ) : (
        <ChangeRow series={series} />
      )}
    </div>
  );
}

/** The backend's own 24h / 7d / 30d values, and nothing else.
 *
 * A window the backend returned as null is absent from `changes` already, so
 * it simply has no cell here - never a dash, never a 0%, never a greyed
 * placeholder holding its place. When every window is null the whole row
 * disappears and the latest price stands alone, which is the truthful outcome
 * for a series the backend could not measure a change on.
 *
 * Movement is typographic, not chromatic: a fall is the same colour as a rise,
 * with a sign to say which it was. Red for an ordinary price decline is
 * trading-terminal vocabulary this product does not use on a collector page.
 */
function ChangeRow({ series }: { series: PriceHistorySeriesView }) {
  if (series.changes.length === 0) return null;

  return (
    <dl className="mt-1.5 flex flex-wrap items-baseline gap-x-4 gap-y-1">
      {series.changes.map((change) => (
        <div key={change.label} className="flex items-baseline gap-1.5">
          <dt className="mono text-[10px] uppercase tracking-wider text-text-faint">
            {change.label}
          </dt>
          <dd className="mono tabular text-[11px] text-text-secondary">
            {change.pct > 0 ? "+" : ""}
            {change.pct.toFixed(2)}%
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** A source whose every reading was disqualified by source semantics.
 *
 * The raw number stays visible - it is what the source really published, and
 * a collector checking SNKRDUNK will see it there - but it is stated as a
 * platform limit rather than drawn as a price. The wording comes from
 * @/lib/sourceConstraint, the same module the Market Index source panels use,
 * so a constrained value is described identically wherever it appears and this
 * component restates no rule of its own.
 *
 * An unrecognised constraint name (a future backend rule this build predates)
 * gets the chip omitted rather than a guessed label: the value is still shown
 * and still marked as not-market-evidence, which is true whatever the new name
 * turns out to mean.
 *
 * DELIBERATELY SHORTER THAN THE SOURCE PANEL. The constraint's full sentence
 * ("This value is at the source's minimum listing price...") is already on
 * screen a few centimetres above, in the "Market sources" panel for the same
 * source, and printing it twice made the page read as if two different things
 * were being explained. This row keeps the shared chip - so the two are
 * recognisably the same fact - and adds only what is new here: why this series
 * has no line. The wording still comes from @/lib/sourceConstraint, so neither
 * surface restates a rule of its own.
 */
function ConstrainedSeriesRow({ series }: { series: PriceHistorySeriesView }) {
  const copy = describeSourceConstraint(series.constraint);

  return (
    <div className="rounded-panel border border-border-muted bg-bg-elevated/50 px-3 py-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-text-secondary">
          {series.label}
          {copy && (
            <span className="inline-flex rounded border border-border-muted bg-bg-card/70 px-1.5 py-px text-[10px] font-medium leading-4 text-text-secondary">
              {copy.label}
            </span>
          )}
        </span>
        <span className="mono tabular text-sm font-medium text-text-primary">
          {formatJpy(series.constrainedLatestJpy)}
        </span>
      </div>
      <p className="mt-1 text-[11px] leading-snug text-text-faint">
        {constrainedSpan(series)}Not treated as a market price
      </p>
    </div>
  );
}

/** How long this source has been reporting nothing but a constrained value.
 *
 * This is the history section's own contribution to a constrained series, and
 * the reason the row is not simply a second copy of the Market Index source
 * panel above: the panel knows the latest value, and only the history knows
 * that it has been that value for eleven readings since the 20th. A single
 * reading has no span to report and says nothing here.
 */
function constrainedSpan(series: PriceHistorySeriesView): string {
  if (series.constrainedCount < 2 || !series.constrainedFirstAt) return "";
  const first = formatDate(series.constrainedFirstAt);
  const last = formatDate(series.constrainedLatestAt);
  const readings = `${series.constrainedCount} readings`;
  // One calendar day of repeated readings is a count, not a span.
  const span = first === last ? first : `${first} – ${last}`;
  return `${readings}, ${span} · `;
}
