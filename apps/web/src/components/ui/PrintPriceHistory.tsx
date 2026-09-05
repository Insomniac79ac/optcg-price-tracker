"use client";

import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatDate, formatJpy } from "@/lib/format";
import { type PriceHistorySeriesView, type PriceHistoryView } from "@/lib/printPriceHistory";
import {
  buildSeriesChartModel,
  formatSeriesDay,
  isDefaultSelected,
  PRINT_SERIES_WINDOWS,
  selectableSeries,
  seriesDisplayLabel,
  seriesInstrumentLabel,
  seriesPaintOrder,
  seriesPlatformLabel,
  WINDOW_LABEL,
  type PrintSeries,
  type PrintSeriesHistory,
  type PrintSeriesWindow,
  type SeriesChartRow,
  type SeriesPointDetail,
} from "@/lib/printSeries";
import { BANDAI, SNKRDUNK, YUYUTEI } from "@/lib/prints";
import { describeSourceConstraint } from "@/lib/sourceConstraint";

/** Supporting evidence beneath the Market Index - never the centre of the page.
 *
 * Everything here is 10-13px metadata on the page's own surfaces, the chart is
 * 168px tall, and the controls are chips rather than a panel. A collector
 * arriving at a print should still read artwork, identity, then index; this
 * answers "and how has that moved, and did the platforms agree?" for the
 * reader who goes looking, without competing for the first glance.
 *
 * There is no candlestick, no volume, no range band, no red/green movement
 * treatment and no interpolation across a break. A decline is drawn in the
 * same stroke as a rise, because a collector looking at a card they own is not
 * a position holder being warned.
 *
 * TWO PAYLOADS, TWO JOBS. The CHART comes from `GET /prints/{id}/series` via
 * @/lib/printSeries: Market Index and each platform as separate named series,
 * segmented by the server wherever the measurement changed. The ROWS beneath
 * it come from `GET /prints/{id}/prices` via @/lib/printPriceHistory: each
 * source's latest price, the backend's own change windows, and the
 * explanation a wholly-constrained source has earned. Neither derives the
 * other's numbers.
 */

/** One quiet stroke per platform.
 *
 * Gold is the Market Index's own colour everywhere else on this page, so the
 * index line takes it and no platform may: a source line in gold would read as
 * a second index. Teal is the product's "trusted information" accent and
 * parchment its neutral ink.
 *
 * `--signal-green` and `--signal-red` are deliberately absent from the
 * fallback ramp as well as the map. A generated hue for an unknown platform
 * must not be the one a reader has been trained to read as "up" or "down" -
 * these are four different platforms, not four verdicts.
 */
const SERIES_COLOR: Record<string, string> = {
  [YUYUTEI]: "var(--accent-teal)",
  [SNKRDUNK]: "var(--parchment)",
  [BANDAI]: "var(--signal-blue)",
};

const MARKET_INDEX_COLOR = "var(--accent-gold)";

/** Hues for a platform this build has never heard of, assigned by the order
 * the server returned it. Enough to keep two unknown sources apart on one
 * chart; never a claim about either. */
const FALLBACK_COLORS = ["var(--signal-purple)", "var(--accent-coral)", "var(--text-muted)"];

function seriesColorFor(series: { kind: string; source: string | null }, index: number): string {
  if (series.kind === "market_index") return MARKET_INDEX_COLOR;
  const mapped = series.source ? SERIES_COLOR[series.source] : undefined;
  return mapped ?? FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}

/** Whether this print's history has arrived yet.
 *
 * The print itself and its history are separate requests, and the page shows
 * the card as soon as the first lands rather than holding the hero back for
 * supporting evidence. That makes the section's arrival a layout event, which
 * is what `loading` exists to absorb - see PrintPriceHistorySection. */
export type PriceHistoryStatus = "loading" | "ready" | "unavailable";

export interface PrintPriceHistorySectionProps {
  status: PriceHistoryStatus;
  view: PriceHistoryView | null;
  /** The `/series` payload for `window`, or null while it is in flight or
   * after it failed. The chart is supporting evidence for supporting
   * evidence: its absence costs the section its chart, never the rows. */
  series: PrintSeriesHistory | null;
  seriesLoading: boolean;
  window: PrintSeriesWindow;
  onWindowChange: (window: PrintSeriesWindow) => void;
}

/** The section, including the space it occupies before it has anything to say.
 *
 * WHY A PLACEHOLDER AND NOT JUST `null`. History is fetched separately from
 * the print, so rendering nothing until it resolves would drop a heading, a
 * chart and two rows into the middle of the page a moment after the card
 * appears, shoving "About this print" and "Other printings" down under the
 * reader's eyes. The placeholder holds approximately the room the real section
 * takes, so the page settles once rather than twice.
 *
 * It is deliberately mute - a heading and empty surfaces, no shimmer, no
 * spinner, no invented number. It claims that something is coming, which is
 * true, and nothing about what.
 *
 * `unavailable` renders nothing at all: a print no source has ever priced, or
 * a history request that failed, is a page without this section rather than a
 * page with an apology in it. A `/series` payload that DID arrive keeps the
 * section alive on its own, so a print with archived index history but no
 * surviving observations still charts.
 */
export function PrintPriceHistorySection({
  status,
  view,
  series,
  seriesLoading,
  window,
  onWindowChange,
}: PrintPriceHistorySectionProps) {
  const chartable = selectableSeries(series).length > 0;
  if (status === "loading") return <PriceHistoryPlaceholder />;
  if ((status === "unavailable" || !view) && !chartable) return null;
  return (
    <PrintPriceHistory
      view={view}
      series={series}
      seriesLoading={seriesLoading}
      window={window}
      onWindowChange={onWindowChange}
    />
  );
}

function PriceHistoryPlaceholder() {
  return (
    <section className="mt-7 border-t border-border-muted pt-5" aria-hidden="true">
      <h2 className="mono text-[10px] font-medium uppercase leading-none tracking-[0.16em] text-text-muted">
        Price history
      </h2>
      <div className="mt-2.5 h-[168px] rounded-panel border border-border-muted/60 bg-bg-elevated/30" />
      <div className="mt-3 grid gap-2.5">
        <div className="h-[58px] rounded-panel border border-border-muted/60 bg-bg-elevated/30" />
        <div className="h-[58px] rounded-panel border border-border-muted/60 bg-bg-elevated/30" />
      </div>
    </section>
  );
}

export function PrintPriceHistory({
  view,
  series,
  seriesLoading,
  window,
  onWindowChange,
}: {
  view: PriceHistoryView | null;
  series: PrintSeriesHistory | null;
  seriesLoading: boolean;
  window: PrintSeriesWindow;
  onWindowChange: (window: PrintSeriesWindow) => void;
}) {
  const rows = view?.series ?? [];
  const available = useMemo(() => selectableSeries(series), [series]);

  // WHY EXCLUSIONS RATHER THAN A SELECTION SET. The chip set changes under the
  // reader whenever the window does - a platform with nothing in 7d appears
  // once ALL is asked for. Storing what was TURNED OFF means a newly-arrived
  // platform is on by default (which is what "default: Market Index plus every
  // primary source" means at every window), while a platform the reader
  // dismissed stays dismissed across window changes. Storing the positive set
  // would have to guess which of those two a key's absence meant.
  const [excluded, setExcluded] = useState<ReadonlySet<string>>(() => new Set<string>());
  // The opposite case: a non-default series (an auxiliary one, the day the API
  // offers any) is off until the reader asks for it.
  const [included, setIncluded] = useState<ReadonlySet<string>>(() => new Set<string>());

  const isSelected = (entry: PrintSeries) =>
    isDefaultSelected(entry) ? !excluded.has(entry.key) : included.has(entry.key);

  const selectedKeys = useMemo(
    () =>
      new Set(
        available
          .filter((entry) =>
            isDefaultSelected(entry) ? !excluded.has(entry.key) : included.has(entry.key),
          )
          .map((entry) => entry.key),
      ),
    [available, excluded, included],
  );

  const model = useMemo(
    () => buildSeriesChartModel(series, selectedKeys),
    [series, selectedKeys],
  );

  // SELECTED, BUT WITH NOTHING ON THE LINE. A platform whose every reading in
  // this window is disqualified (SNKRDUNK quoting its ¥1,000 floor) has points
  // but no stroke, so a lit chip beside it asserts a line that is not there -
  // the same untruth as a lit Market Index chip with no gold on the plot. The
  // chip says so instead, and the chart carries the reason.
  const unplottedKeys = useMemo(
    () =>
      new Set(
        model.series.filter((entry) => entry.plottedCount === 0).map((entry) => entry.key),
      ),
    [model],
  );

  function toggle(entry: PrintSeries) {
    const on = isSelected(entry);
    if (isDefaultSelected(entry)) {
      setExcluded((current) => {
        const next = new Set(current);
        if (on) next.add(entry.key);
        else next.delete(entry.key);
        return next;
      });
      return;
    }
    setIncluded((current) => {
      const next = new Set(current);
      if (on) next.delete(entry.key);
      else next.add(entry.key);
      return next;
    });
  }

  // A print nothing has ever priced and nothing has ever indexed has no
  // section - not an empty-state box.
  if (rows.length === 0 && available.length === 0 && !seriesLoading) return null;

  return (
    <section className="mt-7 border-t border-border-muted pt-5">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h2 className="mono text-[10px] font-medium uppercase leading-none tracking-[0.16em] text-text-muted">
          Price history
        </h2>
        <WindowControl window={window} onChange={onWindowChange} />
      </div>

      {available.length > 0 && (
        <SeriesSelector
          series={available}
          selectedKeys={selectedKeys}
          unplottedKeys={unplottedKeys}
          colorFor={(entry, index) => seriesColorFor(entry, index)}
          onToggle={toggle}
        />
      )}

      <SeriesChartArea
        model={model}
        loading={seriesLoading}
        hasPayload={series !== null}
        hasSelectableSeries={available.length > 0}
        selectedCount={selectedKeys.size}
      />

      {rows.length > 0 && (
        <div className="mt-3 grid gap-2.5">
          {rows.map((entry) => (
            <SeriesRow key={entry.key} series={entry} />
          ))}
        </div>
      )}
    </section>
  );
}

/** 7D / 30D / All.
 *
 * Three windows, because three are what the backend implements. There is
 * deliberately no 90D: offering one would either send a window the API
 * rejects or quietly show ALL under a label promising 90 days, and "All" is
 * already the honest name for whatever history exists - it claims a span of
 * exactly nothing. */
function WindowControl({
  window,
  onChange,
}: {
  window: PrintSeriesWindow;
  onChange: (window: PrintSeriesWindow) => void;
}) {
  return (
    <div
      className="flex items-center gap-0.5 rounded-control border border-border-muted p-0.5"
      role="group"
      aria-label="History window"
      data-testid="price-history-window"
    >
      {PRINT_SERIES_WINDOWS.map((value) => {
        const active = value === window;
        return (
          <button
            key={value}
            type="button"
            onClick={() => onChange(value)}
            aria-pressed={active}
            // An inactive window is a control the reader is meant to be able
            // to read and press, not a disabled one: text-faint is 3.12:1 on
            // this ground (docs/brand.md "Contrast decisions"), which is a
            // caption weight, not a control weight.
            className={`mono rounded-[4px] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 ${
              active
                ? "bg-bg-card text-text-primary"
                : "text-text-muted hover:text-text-secondary"
            }`}
          >
            {WINDOW_LABEL[value]}
          </button>
        );
      })}
    </div>
  );
}

/** Which platforms are on the chart, and the control for changing that.
 *
 * The chip IS the legend - one control rather than a legend plus a filter
 * beside it, which on a 390px column is the difference between a compact strip
 * and an analytics panel. Its colour swatch is the stroke the platform is
 * drawn in, so a reader identifies a line by looking at the thing they used to
 * turn it on.
 *
 * IT CARRIES THE INSTRUMENT TOO, in fainter type: "Yuyu-Tei · Retail price"
 * and "SNKRDUNK · Current listing" are different claims about a card, and a
 * legend naming only the platforms would put a shop's asking price and a
 * marketplace's cheapest open listing on one chart as if they were the same
 * measurement. The platform stays the emphasised half, because that is what
 * the chip TOGGLES; Market Index carries no suffix, because it is not quoted
 * in an instrument at all.
 *
 * Only series the server reported as available appear. A platform Atlas does
 * not collect, and one that has nothing in this window, are both real answers
 * - but neither gives the reader anything to toggle, and a dead control beside
 * three live ones reads as a platform that is broken rather than one that is
 * quiet.
 */
function SeriesSelector({
  series,
  selectedKeys,
  unplottedKeys,
  colorFor,
  onToggle,
}: {
  series: PrintSeries[];
  selectedKeys: ReadonlySet<string>;
  /** Selected, but with nothing drawable in this window. */
  unplottedKeys: ReadonlySet<string>;
  colorFor: (entry: PrintSeries, index: number) => string;
  onToggle: (entry: PrintSeries) => void;
}) {
  return (
    <div
      className="mt-2.5 flex flex-wrap items-center gap-1.5"
      role="group"
      aria-label="Series shown"
      data-testid="price-history-series-selector"
    >
      {series.map((entry, index) => {
        const on = selectedKeys.has(entry.key);
        const noLine = on && unplottedKeys.has(entry.key);
        const color = colorFor(entry, index);
        const instrument = seriesInstrumentLabel(entry);
        return (
          <button
            key={entry.key}
            type="button"
            onClick={() => onToggle(entry)}
            aria-pressed={on}
            // The visible chip is two elements - an emphasised platform and a
            // fainter instrument - and the accessible-name algorithm trims each
            // element's text before joining them, which runs the two halves
            // together as "Yuyu-Tei· Retail price". Naming the control
            // explicitly from the same function the lines and tooltip use keeps
            // what a screen reader announces identical to what is drawn.
            aria-label={
              noLine
                ? `${seriesDisplayLabel(entry)} — nothing to plot in this window`
                : seriesDisplayLabel(entry)
            }
            // A deselected chip is OFF, not unavailable - it is the control
            // the reader turns the platform back on with, so its label stays
            // at a readable weight and the muted border carries the state.
            className={`inline-flex items-center gap-1.5 rounded-control border px-2 py-1 text-[11px] leading-none transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 ${
              on
                ? "border-border-default bg-bg-elevated text-text-primary"
                : "border-border-muted text-text-muted hover:text-text-secondary"
            }`}
          >
            {/* A SOLID rule means "this is drawn". A series that is on but has
                no stroke gets a broken rule instead, so the swatch never
                promises a line the plot does not contain. */}
            <span
              aria-hidden="true"
              className="inline-block h-px w-3.5 shrink-0 rounded"
              style={
                noLine
                  ? {
                      backgroundImage: `repeating-linear-gradient(to right, ${color} 0 2px, transparent 2px 4px)`,
                    }
                  : { backgroundColor: on ? color : "var(--text-faint)" }
              }
            />
            <span className="text-left">
              {seriesPlatformLabel(entry)}
              {/* The instrument is the quieter half, but it is load-bearing -
                  "Retail price" and "Current listing" are different claims
                  about the card - so it is de-emphasised by one step, not
                  faded to the edge of legibility. */}
              {instrument && (
                <span className={on ? "text-text-muted" : ""}>{` · ${instrument}`}</span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** The plot, or the honest sentence that stands in for it. */
function SeriesChartArea({
  model,
  loading,
  hasPayload,
  hasSelectableSeries,
  selectedCount,
}: {
  model: ReturnType<typeof buildSeriesChartModel>;
  loading: boolean;
  hasPayload: boolean;
  hasSelectableSeries: boolean;
  selectedCount: number;
}) {
  // A chart already on screen STAYS on screen while the next window loads,
  // dimmed rather than replaced. Swapping it for the placeholder would flash
  // plot -> grey box -> plot on every press of a control that is meant to read
  // as a filter, and would unmount and remount Recharts' responsive container
  // each time for a payload that usually differs by a handful of points.
  if (model.hasPoints) return <SeriesChart model={model} dimmed={loading} />;

  if (loading) {
    return (
      <div
        className="mt-2 h-[168px] rounded-panel border border-border-muted/60 bg-bg-elevated/30"
        aria-hidden="true"
      />
    );
  }

  return (
    <EmptyChartState
      hasPayload={hasPayload}
      hasSelectableSeries={hasSelectableSeries}
      selectedCount={selectedCount}
    />
  );
}

/** What to say when there is nothing on the axis.
 *
 * Three different facts, three different sentences, and the distinctions are
 * the point: a chart request that failed is not the same as a window that
 * holds no history, which is not the same as a reader who turned every
 * platform off. None of them is an error, none is styled as one, and none of
 * them implies the card has no price - the Market Index above resolves at
 * request time and is unaffected by anything this section can or cannot draw.
 *
 * There is deliberately no fourth sentence for "this print has no history at
 * all". That state has no section: when neither payload holds anything,
 * PrintPriceHistory renders nothing rather than an empty box explaining
 * itself, exactly as it did before this chart existed.
 */
function EmptyChartState({
  hasPayload,
  hasSelectableSeries,
  selectedCount,
}: {
  hasPayload: boolean;
  hasSelectableSeries: boolean;
  selectedCount: number;
}) {
  const message = !hasPayload
    ? "Price chart unavailable right now."
    : !hasSelectableSeries
      ? "No recorded price history in this window."
      : selectedCount === 0
        ? "Select a platform to chart."
        : "No plotted prices for the selected platforms in this window.";

  return (
    <div
      className="mt-2 flex h-[168px] items-center justify-center rounded-panel border border-border-muted/60 bg-bg-elevated/20 px-4 text-center"
      data-testid="price-history-empty"
    >
      {/* The PRIMARY line of an empty state, so it takes the same weight
          CollectorEmptyState gives its title - text-faint is reserved for the
          secondary line, and this sentence is the only content in the box. */}
      <p className="text-[11px] leading-snug text-text-secondary">{message}</p>
    </div>
  );
}

/** One line per STROKE, not per series.
 *
 * That is the whole mechanism behind "never draw across a boundary". A series
 * arrives here already split - by the server wherever the measurement changed
 * (a Market Index v2 -> v3 methodology change, a source moving from a listing
 * floor to a sales median), and by @/lib/printSeries again wherever a point is
 * not a market price - and each piece is a separate <Line> with its own
 * dataKey. There is no path between two strokes for the renderer to stroke,
 * so v1 -> v2 -> v3 cannot become one uninterrupted line however the data
 * moves.
 *
 * `connectNulls` is on WITHIN a stroke, and only there: a null inside one is
 * another platform's observation day, which this series genuinely continued
 * across. Dots mark the days this series actually observed, so the reader can
 * see where the evidence is rather than inferring it from a smooth line - and
 * a one-point stroke renders as exactly one dot and no line.
 *
 * Animation is off outright rather than gated on a media query: this is a
 * static evidence chart, and a line that draws itself on every mount is motion
 * with nothing to say.
 */
function SeriesChart({
  model,
  dimmed,
}: {
  model: ReturnType<typeof buildSeriesChartModel>;
  dimmed: boolean;
}) {
  const colorByStroke = new Map<string, string>();
  const colorBySeries = new Map<string, string>();
  model.series.forEach((entry, index) => {
    const color = seriesColorFor(entry, index);
    colorBySeries.set(entry.key, color);
    for (const stroke of entry.strokes) colorByStroke.set(stroke.dataKey, color);
  });

  // Paint order only - the legend, the tooltip and the colours all still read
  // the server's own order. See seriesPaintOrder for why the index goes on top.
  const orderedSeries = seriesPaintOrder(model.series);

  // Whose measurement changed. A break belongs to ONE series, and naming them
  // is what stops the caption below claiming something the reader can see is
  // false: on a print where the index broke but a platform did not, the
  // platform's line legitimately runs straight through the marks.
  const unplottedLabels = model.series
    .filter((entry) => entry.plottedCount === 0)
    .map((entry) => entry.label);

  const brokenSeriesLabels = [
    ...new Set(
      model.breaks.map(
        (entry) => model.series.find((s) => s.key === entry.seriesKey)?.label ?? "",
      ),
    ),
  ].filter((label) => label !== "");

  return (
    <>
      <div
        // Recharts puts a tabIndex on its own root, so a tap or a Tab lands
        // here and the UA paints its default white outline over the plot -
        // loud, and off-brand beside the teal ring the chips and the window
        // control use. Same ring, applied to whatever inside actually takes
        // focus.
        className={`mt-2 h-[168px] w-full transition-opacity [&_*:focus]:outline-none [&_*:focus-visible]:rounded-panel [&_*:focus-visible]:outline-none [&_*:focus-visible]:ring-2 [&_*:focus-visible]:ring-accent-teal/60 ${dimmed ? "opacity-50" : ""}`}
        aria-busy={dimmed || undefined}
        data-testid="price-history-chart"
      >
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={model.rows} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border-muted)" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(value: number) =>
                formatSeriesDay(new Date(value).toISOString().slice(0, 10))
              }
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
              // series that never moved, a fitted axis lands on ¥218-¥222
              // around a flat ¥220 line and invites the reader to see one-yen
              // movement that is not there; padding the domain keeps a flat
              // price looking flat. It changes the axis only - no point's
              // value is altered.
              domain={[
                (min: number) => Math.floor(min * 0.95),
                (max: number) => Math.ceil(max * 1.05),
              ]}
            />
            <Tooltip
              cursor={{ stroke: "var(--border-default)", strokeWidth: 1 }}
              content={<SeriesTooltip />}
              isAnimationActive={false}
            />
            {/* A methodology or instrument change, marked where it happened.
                Hairline, dashed and behind the lines: the reader can see WHY
                two pieces of one platform do not meet, without the chart
                implying something went wrong.

                TINTED TO THE SERIES IT BELONGS TO. In the grid's neutral grey
                a mark read as a property of the whole chart, so on a print
                where only the index broke, an untinted dash stood over a
                platform line that crossed it unbroken - next to a caption
                promising lines are never joined across a mark. The colour ties
                each mark to the one line it actually interrupts. */}
            {model.breaks.map((entry) => (
              <ReferenceLine
                key={`${entry.seriesKey}:${entry.t}:${entry.reason}`}
                x={entry.t}
                stroke={colorBySeries.get(entry.seriesKey) ?? "var(--border-default)"}
                strokeOpacity={0.5}
                strokeDasharray="2 3"
                strokeWidth={1}
                ifOverflow="extendDomain"
              />
            ))}
            {/* THE MARKET INDEX IS DRAWN LAST AND THINNEST, deliberately.
                It is Atlas's combination of the platforms beneath it, so on
                any print with a single eligible source it holds exactly that
                source's value and the two series occupy identical pixels.
                Painted in series order at equal width, the index went under
                the source and vanished - a lit gold chip with no gold anywhere
                on the plot, which is the one thing this section promises not
                to do.

                Drawing it last puts it on top; drawing it NARROWER leaves the
                platform beneath it showing as a halo either side. Agreement
                then reads as a gold core inside a coloured edge - both series
                visible, neither displaced, and no point moved off its real
                value to fake the separation. */}
            {orderedSeries.flatMap((entry) => {
              const isIndex = entry.kind === "market_index";
              return entry.strokes.map((stroke) => (
                <Line
                  key={stroke.dataKey}
                  type="monotone"
                  dataKey={stroke.dataKey}
                  name={entry.label}
                  stroke={colorByStroke.get(stroke.dataKey)}
                  strokeWidth={isIndex ? 1.25 : 2}
                  dot={{
                    r: isIndex ? 1.4 : 1.9,
                    strokeWidth: 0,
                    fill: colorByStroke.get(stroke.dataKey),
                  }}
                  activeDot={{ r: 2.8, strokeWidth: 0 }}
                  connectNulls
                  isAnimationActive={false}
                />
              ));
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {/* NAMES WHOSE MEASUREMENT CHANGED, because the unqualified version
          ("Lines are not joined across them") was falsifiable on screen: a
          platform that did not break runs straight through a mark belonging to
          one that did, and the reader can see it. Naming the series makes the
          sentence true of exactly the line it describes. */}
      {/* Names any platform the reader has switched ON that has no line here,
          and why. Without it the chip is lit, the plot is empty of that
          colour, and the reader is left to guess whether the platform is
          broken or the card simply is not traded there. */}
      {unplottedLabels.length > 0 && (
        <p className="mt-1.5 text-[10px] leading-snug text-text-muted">
          {unplottedLabels.join(", ")}
          {unplottedLabels.length === 1 ? " has " : " have "}
          no market price to plot in this window — see the readings below.
        </p>
      )}
      {brokenSeriesLabels.length > 0 && (
        <p className="mt-1.5 text-[10px] leading-snug text-text-muted">
          {brokenSeriesLabels.length === 1
            ? `Dashed marks show where the measurement changed for ${brokenSeriesLabels[0]}. Its line is not joined across them.`
            : `Dashed marks show where the measurement changed, in each platform's own colour: ${brokenSeriesLabels.join(", ")}. Those lines are not joined across them.`}
        </p>
      )}
    </>
  );
}

/** What one day held, per selected platform.
 *
 * The date, who quoted it and what the number was - and for a reading that is
 * not a market price, the fact that it is not, in @/lib/sourceConstraint's own
 * words. There is no confidence, no reliability score, no agreement
 * percentage and no day-over-day change: a difference this component computed
 * between two adjacent points would be a number no other surface in the
 * product agrees with, and the backend's own change windows are already in the
 * rows below.
 */
function SeriesTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload?: SeriesChartRow }[];
}) {
  const row = active ? payload?.[0]?.payload : undefined;
  if (!row) return null;

  return (
    // WIDTH IS CAPPED so the longest line wraps instead of widening the page.
    // A caveat like "SNKRDUNK · Current listing: Minimum listing price · not
    // treated as a market price" sized the box to its own length, and on a
    // 390px screen that pushed the document 39px wider than the viewport -
    // the one thing this section is not allowed to do.
    <div className="max-w-[min(15rem,calc(100vw-2.5rem))] rounded-panel border border-border-default bg-bg-surface px-2.5 py-2 shadow-lg">
      <p className="mono text-[10px] uppercase tracking-wider text-text-faint">
        {formatSeriesDay(row.day)}
      </p>
      <ul className="mt-1.5 grid gap-1">
        {row.detail.map((detail, index) => (
          <li key={`${detail.seriesKey}:${index}`} className="flex items-baseline gap-3">
            <span className="min-w-0 break-words text-[11px] leading-tight text-text-secondary">
              {detail.label}
            </span>
            <span className="mono tabular ml-auto shrink-0 text-[11px] font-medium text-text-primary">
              {formatJpy(detail.valueJpy)}
            </span>
          </li>
        ))}
      </ul>
      {row.detail.map((detail, index) =>
        detailCaveat(detail) ? (
          <p
            key={`caveat:${detail.seriesKey}:${index}`}
            className="mt-1 text-[10px] leading-snug text-text-faint"
          >
            {detailCaveat(detail)}
          </p>
        ) : null,
      )}
    </div>
  );
}

/** The one extra sentence a point may need, or nothing.
 *
 * Only two points ever earn one, and both are cases where a number is on
 * screen that is not a price this card traded at:
 *
 *   a constrained source reading - the platform's own floor rather than the
 *   card's, described in @/lib/sourceConstraint's words so it reads the same
 *   here as in the Market Index source panel above;
 *
 *   an archived index day with no value - no source was eligible, which is a
 *   recorded result and never a zero.
 *
 * A constraint name this build has never heard of gets the generic sentence
 * rather than a guessed label: "not treated as a market price" is true
 * whatever the new rule turns out to mean.
 */
function detailCaveat(detail: SeriesPointDetail): string | null {
  if (detail.plotted) return null;
  if (detail.valueJpy === null) return `${detail.label}: no value recorded that day`;
  const copy = describeSourceConstraint(detail.constraint);
  return copy
    ? `${detail.label}: ${copy.label} · not treated as a market price`
    : `${detail.label}: not treated as a market price`;
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
