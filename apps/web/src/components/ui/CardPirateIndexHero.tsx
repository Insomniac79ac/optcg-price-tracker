"use client";

import { useState } from "react";
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

import { AtlasMark } from "@/components/brand/AtlasMark";
import { WindowTokenControl } from "@/components/ui/WindowTokenControl";
import {
  VERSION_BREAK_REASONS,
  formatAbsoluteChange,
  isSnapshotGap,
  formatCoveredRange,
  formatIndexDay,
  formatLevel,
  formatPctChange,
  indexDomain,
  splitRuns,
  windowLabel,
  windowProse,
  type IndexBreak,
  type IndexSeries,
  type IndexWindowRow,
} from "@/lib/cardPirateIndex";
import {
  buildIndexExport,
  downloadIndexExport,
  resolveExportFonts,
} from "@/lib/indexChartExport";

/** The Card Pirate Index, at the top of /analytics.
 *
 * WHAT THIS SECTION IS FOR, and the hierarchy it claims: /analytics used to
 * open on four coverage tiles - how much of the catalogue Atlas can price -
 * and closed with a paragraph explaining that it could not answer a movement
 * question at all. The index answers it. So the index leads, the chart is the
 * largest thing above the fold, and the coverage statistics become the
 * supporting material they always were.
 *
 * EVERY NUMBER HERE IS THE SERVER'S. The level, the change, the period high
 * and low, the covered range, and whether the requested window is covered all
 * arrive decided. There is no client-side re-derivation of a change from
 * `points[]`, no alternate history computed from a longer window, and no
 * padding of a short series to fill a control's label - see
 * `@/lib/cardPirateIndex` for why that rule is absolute rather than tidy.
 */

export type IndexStatus = "loading" | "ready" | "error";

export interface CardPirateIndexHeroProps {
  /** The settled series for `window`, or null while the first one is in
   * flight or the request failed. */
  series: IndexSeries | null;
  status: IndexStatus;
  /** True while a NEWER window than `series` answers is still loading. The
   * previous chart stays on screen, dimmed, rather than collapsing. */
  refreshing: boolean;
  /** The token currently selected. A plain string because the vocabulary is
   * the server's; `windows` below is what it is legal against. */
  window: string;
  onWindowChange: (window: string) => void;
}

export function CardPirateIndexHero({
  series,
  status,
  refreshing,
  window,
  onWindowChange,
}: CardPirateIndexHeroProps) {
  return (
    <section className="panel px-4 py-4 sm:px-5 sm:py-5" data-testid="index-hero">
      <div className="flex flex-wrap items-start justify-between gap-3">
        {/* The page's H1. /analytics has exactly one subject now, and this is
            it - the eyebrow above this panel and the "Current market
            landscape" H2 below both hang off it. See PageFrame in
            app/analytics/page.tsx for why the old H1 moved. */}
        <h1 className="font-display text-[22px] font-semibold leading-[1.15] tracking-tight text-text-primary sm:text-[26px]">
          Card Pirate Index
        </h1>
        <WindowTokenControl
          window={window}
          windows={series?.windows ?? []}
          onChange={onWindowChange}
          disabled={status === "error"}
          shortfallFor={windowShortfall}
          label="Index window"
          testId="index-window"
        />
      </div>

      {status === "error" ? (
        <p className="mt-4 text-sm text-text-secondary">
          The index could not be loaded. Please try again shortly.
        </p>
      ) : !series ? (
        <IndexHeroSkeleton />
      ) : (
        <div
          aria-busy={refreshing}
          className={
            refreshing ? "opacity-60 transition-opacity motion-reduce:transition-none" : ""
          }
        >
          <IndexHeadline series={series} />
          <IndexChart series={series} />
          <IndexExportAction series={series} />
          <IndexFootnotes series={series} window={window} />
        </div>
      )}
    </section>
  );
}

/** Level first, then the change, then the period's own bounds.
 *
 * The level is the largest type on the page by some margin, because "where is
 * the market" is the question this page now exists to answer and everything
 * else on screen qualifies it.
 */
function IndexHeadline({ series }: { series: IndexSeries }) {
  const level = formatLevel(series.current_value);
  return (
    <div className="mt-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span
          className="font-display text-[40px] font-semibold leading-none tracking-tight text-text-primary sm:text-[52px]"
          data-testid="index-level"
        >
          {level ?? "—"}
        </span>
        <IndexChangeReadout series={series} />
      </div>

      <dl className="mt-4 grid grid-cols-3 gap-x-3 gap-y-2 border-t border-border-muted pt-3 sm:max-w-md">
        <IndexStat label="Start" value={formatLevel(series.starting_value)} testId="index-start" />
        <IndexStat label="High" value={formatLevel(series.high_value)} testId="index-high" />
        <IndexStat label="Low" value={formatLevel(series.low_value)} testId="index-low" />
      </dl>
    </div>
  );
}

/** The change, or an honest statement that there is not one.
 *
 * A null change is NOT 0 %. Section 13.2 is explicit that a null renders as an
 * absence rather than a zero or a bare dash - the two look alike on screen and
 * mean opposite things ("the market did not move" versus "this period cannot
 * be compared"). Nothing here falls back to a shorter window to rescue it
 * either; the window the reader selected is the window they are answered in.
 */
function IndexChangeReadout({ series }: { series: IndexSeries }) {
  if (!series.change) {
    return (
      <span
        className="text-[13px] leading-snug text-text-muted"
        data-testid="index-change-unavailable"
      >
        Change not available across this period
      </span>
    );
  }

  const change = series.change;
  const direction = Number(change.absolute);
  // Deliberately NOT red/green: collector-facing price movement never gets the
  // admin surface's signal vocabulary (docs/interface_design_system.md
  // "Do-not list"). Gold marks a real move, parchment marks a flat one.
  const tone = direction === 0 ? "text-text-secondary" : "text-accent-gold";

  return (
    <span className="flex flex-wrap items-baseline gap-x-2" data-testid="index-change">
      <span className={`font-display text-[20px] font-semibold leading-none ${tone}`}>
        {formatAbsoluteChange(change)}
      </span>
      <span className={`text-[15px] font-medium ${tone}`}>{formatPctChange(change)}</span>
      {change.spans_break && (
        <span
          className="mono rounded-[4px] border border-border-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-text-muted"
          title="This span crosses a methodology change. The levels are chain-linked across it; the underlying card prices on either side are not directly comparable."
          data-testid="index-change-break"
        >
          Linked
        </span>
      )}
    </span>
  );
}

function IndexStat({
  label,
  value,
  testId,
}: {
  label: string;
  value: string | null;
  testId: string;
}) {
  return (
    <div>
      <dt className="text-xs font-medium text-text-muted">
        {label}
      </dt>
      <dd className="mt-1 text-[15px] font-medium text-text-secondary" data-testid={testId}>
        {value ?? "—"}
      </dd>
    </div>
  );
}

/** The control, rendered from the SERVER's window list.
 *
 * Not from a token list in this build. Section 12.2 rule 3 makes the `windows`
 * map "the key affordance": it is what lets an unreachable timeframe render as
 * a DISABLED button with a reason, rather than as a clickable path into a
 * chart that cannot answer it. Before TASK INDEX 2A-B the API published no
 * such map, so every button had to stay pressable and the shortfall could only
 * be explained after the fact, underneath.
 *
 * `available` is the server's span test (section 12.2 rule 4) and is never
 * recomputed here from `available_from` and a clock. Rule 5 matters too: a
 * methodology break does NOT make a window unavailable, because the level
 * series is continuous across segments - so a disabled button here always
 * means "the history does not reach back that far", and never "something
 * changed in the middle".
 *
 * AN UNREACHABLE WINDOW IS `aria-disabled`, NOT `disabled`, and that is an
 * accessibility fix rather than a preference. A natively `disabled` button is
 * removed from the tab order in every major browser, so a keyboard user cannot
 * focus it - and a `title` never fires on touch at all. With six of the seven
 * buttons unreachable on a five-day archive, the native form left the majority
 * of this control with no explanation for anyone not using a mouse. Kept
 * focusable, the reason reaches keyboard and screen-reader users through the
 * accessible name, and `windowShortfall` below puts it on screen in text for
 * everyone else.
 */
function windowShortfall(row: IndexWindowRow): string | null {
  if (row.available || row.required_days === null) return null;
  const days = row.covered_days === 1 ? "1 day" : `${row.covered_days} days`;
  return `Atlas has ${days} of index history; this window needs ${row.required_days}.`;
}

/** The chart. The largest object on the page, and the reason it exists.
 *
 * ONE LINE PER RUN, not one line per series - the same mechanism the print
 * page's chart uses. A run ends wherever `step_days > 1` says the archive
 * holds nothing in between, and the two real endpoints are then joined by a
 * separate DASHED stroke. There is no path between two solid runs for the
 * renderer to stroke, so a multi-day gap cannot become an unbroken daily line
 * however the data moves, and no point is invented to fill it (section 13.4).
 *
 * Animation is off outright rather than gated on a media query: a line that
 * draws itself on every window change is motion with nothing to say, and this
 * chart changes on every press of the control above it.
 */
function IndexChart({ series }: { series: IndexSeries }) {
  const domain = indexDomain(series);
  const runs = splitRuns(series.points);
  // Section 13.4, first row: a version boundary is drawn with the LINE
  // CONTINUOUS through it and a vertical rule at the date. The level really is
  // continuous there (section 5.1 rule 4), so dropping the line or leaving a
  // visual gap would contradict the stored data - the marker carries the
  // meaning, the line carries the level. These come from the server's `breaks`
  // and are never inferred from the points.
  const versionBreaks = series.breaks.filter(
    (entry) => !isSnapshotGap(entry),
  );
  // Several boundaries on one date collapse into ONE marker whose tooltip
  // lists them all - section 13.4: "Never hide a marker because the chart is
  // crowded ... never drop one."
  const markers = new Map<string, IndexBreak[]>();
  for (const entry of versionBreaks) {
    const at = markers.get(entry.at);
    if (at) at.push(entry);
    else markers.set(entry.at, [entry]);
  }

  // Recharts needs one row per x value with a key per stroke. Runs never
  // overlap, so a row carries exactly one solid key - plus, on a gap's two
  // endpoints, the dashed connector's key as well.
  const rows = series.points.map((point) => {
    const row: Record<string, number | string | null> = {
      t: Date.parse(`${point.date}T00:00:00Z`),
      date: point.date,
      value: Number(point.value),
      constituents: point.constituent_count,
      eligible: point.eligible_print_count,
      movers_up: point.movers_up,
      movers_down: point.movers_down,
      movers_flat: point.movers_flat,
      step_days: point.step_days,
    };
    return row;
  });

  const byDate = new Map(rows.map((row) => [row.date as string, row]));
  const write = (date: string, key: string, value: number) => {
    const row = byDate.get(date);
    if (row) row[key] = value;
  };
  runs.forEach((run, i) => {
    for (const point of run.points) write(point.date, `run${i}`, Number(point.value));
    if (run.gapFrom) {
      write(run.gapFrom.date, `gap${i}`, Number(run.gapFrom.value));
      write(run.points[0].date, `gap${i}`, Number(run.points[0].value));
    }
  });
  const gapRuns = runs.flatMap((run, i) => (run.gapFrom ? [i] : []));

  if (series.points.length === 0) {
    return (
      <p className="mt-4 text-sm text-text-secondary" data-testid="index-chart-empty">
        No published index points in this window yet.
      </p>
    );
  }

  return (
    <div className="relative mt-5">
      <IndexWatermark />
      <div
        // Recharts puts a tabIndex on its own root, so a tap or a Tab lands
        // here and the UA paints its default white outline over the plot.
        // Same teal ring the window control uses, applied to whatever inside
        // actually takes focus.
        className="relative h-[260px] w-full [&_*:focus-visible]:rounded-panel [&_*:focus-visible]:outline-none [&_*:focus-visible]:ring-2 [&_*:focus-visible]:ring-accent-teal/60 [&_*:focus]:outline-none sm:h-[340px] lg:h-[400px]"
        data-testid="index-chart"
      >
        <ResponsiveContainer width="100%" height="100%">
          {/* `top: 18` leaves room for the break marker's glyph, which is
              drawn at the top of its reference line. At the previous 8 the
              diamond's upper point was clipped by the plot boundary and read
              as a downward caret rather than as a marker. */}
          <LineChart data={rows} margin={{ top: 18, right: 10, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border-muted)" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(value: number) =>
                formatIndexDay(new Date(value).toISOString().slice(0, 10))
              }
              tick={{ fill: "var(--text-faint)", fontSize: 10 }}
              axisLine={{ stroke: "var(--border-muted)" }}
              tickLine={false}
              minTickGap={32}
            />
            <YAxis
              width={62}
              tickFormatter={(value: number) =>
                value.toLocaleString("en-US", { maximumFractionDigits: 0 })
              }
              tick={{ fill: "var(--text-faint)", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              // Section 13.3: at least +/-1 % around the segment base level,
              // widened only by real data. A fitted axis would turn this
              // index's +0.01 % into a mountain range, which is exactly the
              // cosmetic amplification the methodology forbids.
              {...(domain ? { domain, allowDataOverflow: false } : {})}
            />
            <Tooltip
              cursor={{ stroke: "var(--border-default)", strokeWidth: 1 }}
              content={<IndexTooltip breaks={series.breaks} />}
              isAnimationActive={false}
            />
            {[...markers.entries()].map(([at, entries]) => (
              <ReferenceLine
                key={`break:${at}`}
                x={Date.parse(`${at}T00:00:00Z`)}
                stroke="var(--parchment)"
                strokeOpacity={0.6}
                strokeDasharray="2 3"
                strokeWidth={1}
                ifOverflow="extendDomain"
                label={{
                  value: "◆",
                  position: "top",
                  // NOT `--text-faint`. docs/brand.md scopes that token at
                  // 3.12:1 to "decorative/non-essential labels", and a
                  // methodology boundary is the opposite of decorative -
                  // missing it means misreading whether the two sides of the
                  // chart are comparable. 9px also failed the large-text
                  // carve-out that exemption depends on.
                  fill: "var(--text-secondary)",
                  fontSize: 12,
                }}
                // The accessible name says what a sighted reader gets from the
                // marker plus its tooltip: the measurement changed here, and
                // the levels are chain-linked across it.
                aria-label={breakSummary(entries)}
              />
            ))}
            {gapRuns.map((i) => (
              <Line
                key={`gap${i}`}
                type="linear"
                dataKey={`gap${i}`}
                stroke="var(--accent-gold)"
                strokeWidth={1.25}
                strokeDasharray="3 4"
                strokeOpacity={0.7}
                dot={false}
                activeDot={false}
                connectNulls
                isAnimationActive={false}
                legendType="none"
              />
            ))}
            {runs.map((_run, i) => (
              <Line
                key={`run${i}`}
                type="monotone"
                dataKey={`run${i}`}
                name="Card Pirate Index"
                stroke="var(--accent-gold)"
                strokeWidth={2}
                dot={{ r: 2.2, strokeWidth: 0, fill: "var(--accent-gold)" }}
                activeDot={{ r: 4, strokeWidth: 0 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/** What a boundary means, in one sentence, from the SERVER's own fields.
 *
 * Section 13.4 fixes the wording's substance: name what changed, name the
 * carried level, and say plainly that the levels are chain-linked across the
 * point while the underlying card prices on either side are not directly
 * comparable. Nothing here inspects a level to decide that - `carried`,
 * `carried_level` and the version pair are all published.
 *
 * A reason this build does not recognise still produces a sentence. Section
 * 13.4's rule is that a marker is never dropped; a vague marker is a far
 * smaller failure than an unmarked change.
 */
export function breakSummary(entries: IndexBreak[]): string {
  const parts = entries.map((entry) => {
    if (entry.reason === "index_version_change") {
      return `Index version ${entry.from_index_version} → ${entry.to_index_version}`;
    }
    if (entry.reason === "source_semantics_version_change") {
      return `Source semantics ${entry.from_source_semantics_version} → ${entry.to_source_semantics_version}`;
    }
    if (entry.reason === "methodology_version_change") {
      return `Methodology version ${entry.from_methodology_version} → ${entry.to_methodology_version}`;
    }
    return VERSION_BREAK_REASONS.has(entry.reason)
      ? "Measurement method changed"
      : `Series boundary (${entry.reason})`;
  });
  const carried = entries.find((entry) => entry.carried && entry.carried_level !== null);
  const level = carried ? ` Level carried across at ${formatLevel(carried.carried_level)}.` : "";
  const reset = entries.some((entry) => entry.carried === false);
  return (
    `${parts.join("; ")}. Measurement method changed here.${level} ` +
    (reset
      ? "The series restarted at its base level here, so figures are not comparable across this point."
      : "Levels are chain-linked across this point; the underlying card prices on either side are not directly comparable.")
  );
}

/** The Atlas mark, inside the plot, as a watermark.
 *
 * Reused from `@/components/brand/AtlasMark` rather than redrawn - there is
 * one Atlas mark and this is it. `title={null}` renders it `aria-hidden`,
 * which is the correct treatment for decoration: it carries no chart meaning,
 * so a screen reader that announced it would be reading out furniture.
 *
 * PARKED IN THE LOWER-RIGHT, NOT CENTRED, and that is a correction rather than
 * a preference. Centred, it collided with the data in a way that was not a
 * coincidence: `indexDomain` anchors the y-axis on the segment base level, so
 * a near-1000 index draws its line through the vertical middle of the plot -
 * exactly where a vertically-centred mark puts the compass pivot. The line ran
 * through the needle in every capture, which reads as a stray UI element
 * sitting on the data rather than as brand furniture behind it. Down here it
 * sits in the quadrant a flat series leaves empty, and it is smaller.
 *
 * Behind the data and out of the way of it: `z-0` puts it under the plotted
 * line, `pointer-events-none` keeps it out of the tooltip's hit-testing, and
 * it is inset from both axes so it never sits under a tick label. On mobile it
 * shrinks with the plot rather than crowding it.
 */
function IndexWatermark() {
  return (
    <div
      aria-hidden="true"
      // LOWER-LEFT, not lower-right. The tooltip for the newest point renders
      // over the right of the plot, and "today's value" is what a collector
      // hovers most - so the mark spent its time hidden under an opaque box
      // exactly when it was most likely to be looked at.
      className="pointer-events-none absolute bottom-[38px] left-[62px] right-3 top-0 z-0 flex items-end justify-start"
      data-testid="index-watermark"
    >
      <AtlasMark title={null} className="h-[26%] w-auto opacity-[0.07]" />
    </div>
  );
}

/** One day, in the terms the methodology publishes it in.
 *
 * Breadth is first-class here, not a diagnostic. Section 13.3: while movement
 * is sparse, "296 of 296 cards unchanged" is the honest headline for a day,
 * and it says more than a flat line does. So the mover split and the
 * constituent count sit in the tooltip beside the level rather than being
 * hidden as debug detail.
 */
function IndexTooltip({
  active,
  payload,
  breaks = [],
}: {
  active?: boolean;
  payload?: { payload: Record<string, number | string | null> }[];
  breaks?: IndexBreak[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0].payload;
  const date = typeof row.date === "string" ? row.date : null;
  const value = typeof row.value === "number" ? row.value : null;
  if (date === null || value === null) return null;

  const up = row.movers_up;
  const down = row.movers_down;
  const flat = row.movers_flat;
  const hasMovers = typeof up === "number" && typeof down === "number" && typeof flat === "number";
  const step = row.step_days;

  return (
    <div className="rounded-panel border border-border-default bg-bg-elevated px-3 py-2 shadow-lg">
      <p className="mono text-[10px] uppercase tracking-wider text-text-faint">
        {formatIndexDay(date)}
      </p>
      <p className="mt-1 font-display text-[18px] font-semibold leading-none text-text-primary">
        {value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </p>
      {typeof row.constituents === "number" && (
        <p className="mt-1.5 text-[11px] text-text-secondary">
          {row.constituents.toLocaleString("en-US")} cards in the index
          {typeof row.eligible === "number"
            ? ` · ${row.eligible.toLocaleString("en-US")} priced`
            : ""}
        </p>
      )}
      {hasMovers && (
        <p className="mt-0.5 text-[11px] text-text-muted">
          {up} up · {down} down · {flat} unchanged
        </p>
      )}
      {typeof step === "number" && step > 1 && (
        <p className="mt-1 max-w-[16rem] text-[11px] leading-snug text-text-muted">
          {step} days since the previous point — a real multi-day move, not
          interpolation.
        </p>
      )}
      {/* Section 13.4: the marker's tooltip names what changed, the carried
          level, and that the two sides are not directly comparable. */}
      {breaks.some((entry) => entry.at === date && !isSnapshotGap(entry)) && (
        <p
          className="mt-1.5 max-w-[16rem] border-t border-border-muted pt-1.5 text-[11px] leading-snug text-parchment"
          data-testid="index-tooltip-break"
        >
          {breakSummary(breaks.filter((entry) => entry.at === date && !isSnapshotGap(entry)))}
        </p>
      )}
    </div>
  );
}

/** What the chart cannot say for itself.
 *
 * The partial-history line is deliberately quiet - a caption, not a warning.
 * A collector pressing 1Y on a five-day-old archive has not done anything
 * wrong and nothing is broken; the honest answer is to draw what exists and
 * name the span it covers. Padding the chart backward to the requested window
 * would be inventing a year of prices, and greying the button out would claim
 * an availability the API does not publish.
 */
function IndexFootnotes({ series, window }: { series: IndexSeries; window: string }) {
  const covered = formatCoveredRange(series.available_from, series.available_to);
  const prose = windowProse(window);
  const versionBreaks = series.breaks.filter((entry) => !isSnapshotGap(entry));
  const unreachable = series.windows.filter((row) => !row.available);
  return (
    <div className="mt-3 space-y-1.5 border-t border-border-muted pt-3">
      {!series.covers_requested_window && (
        <p className="text-[12px] leading-relaxed text-text-muted" data-testid="index-partial-history">
          {[
            covered ? `Showing available history only — ${covered}.` : "Showing available history only.",
            // `all` has no sentence form because it is not a duration, and
            // neither has a token this build does not recognise. The clause is
            // dropped rather than reworded into a claim about a span the
            // window never asked for.
            prose ? `Atlas has not been recording the index for ${prose} yet.` : null,
          ]
            .filter(Boolean)
            .join(" ")}
        </p>
      )}
      {series.covers_requested_window && covered && (
        <p className="text-[12px] leading-relaxed text-text-muted" data-testid="index-covered-range">
          {covered}
        </p>
      )}
      {/* WHY HALF THE CONTROL IS UNREACHABLE, on screen, for everyone.
          A `title` on each button reaches a mouse and nothing else - not
          touch, and (before these buttons were made focusable) not a keyboard
          either. With six of seven windows unreachable on a five-day archive,
          leaving the reason hover-only meant the majority of this control was
          unexplained for most readers. Named from the server's own
          `covered_days`, never counted from the points. */}
      {unreachable.length > 0 && (
        <p className="text-[12px] leading-relaxed text-text-muted" data-testid="index-window-shortfall">
          {unreachable.map((row) => windowLabel(row.token)).join(", ")}{" "}
          {unreachable.length === 1 ? "needs" : "need"} more history than Atlas
          has recorded so far ({unreachable[0].covered_days === 1
            ? "1 day"
            : `${unreachable[0].covered_days} days`}
          ).
        </p>
      )}
      {/* The markers on the plot are visual; this is the same information in
          text, so a boundary is not something only a sighted reader hovering
          the right pixel can discover. */}
      {versionBreaks.length > 0 && (
        <p
          className="text-[12px] leading-relaxed text-text-secondary"
          data-testid="index-break-note"
        >
          {versionBreaks.length === 1
            ? `One methodology change in this period, on ${formatIndexDay(versionBreaks[0].at)}. `
            : `${versionBreaks.length} methodology changes in this period. `}
          {breakSummary(versionBreaks)}
        </p>
      )}
      <p className="text-[12px] leading-relaxed text-text-faint">
        The index opens at 1,000 and tracks the whole priced One Piece
        catalogue day to day — the price basis and scope filters below narrow
        the coverage statistics, not this. It is not a price, and it is not
        investment advice.
      </p>
    </div>
  );
}

/** "Download chart" - the visible half of the PNG export.
 *
 * DELIBERATELY QUIET, AND DELIBERATELY BELOW THE CHART. The window control is
 * how a reader changes what they are looking at and the chart is what they
 * came for; a save action is neither, so it takes the footnote tier's type
 * scale and sits after the plot rather than competing with the H1. It is one
 * button - no share sheet, no social targets - because a file the reader owns
 * is the whole ask, and anything more would be a second feature wearing this
 * one's clothes.
 *
 * WHAT IT EXPORTS IS WHAT IS ON SCREEN. The plan is built from the `series`
 * this component was handed - the same object the chart above is drawing - so
 * pressing it cannot refetch, cannot re-slice, and cannot produce a picture of
 * a window the reader is not looking at.
 *
 * UNAVAILABLE ONLY WHEN THERE IS NOTHING DRAWABLE - `buildIndexExport`
 * returning null, which happens exactly when the window published no point.
 * It is `aria-disabled` rather than natively `disabled`, for the reason the
 * window control already learned in 2A-B: a natively disabled button leaves
 * the tab order entirely and its `title` never fires on touch, so the one
 * reader most likely to wonder why nothing happens is the one who cannot find
 * out. The reason travels in the accessible name instead, and the click is
 * guarded in the handler.
 *
 * The accessible name names the window, because "Download chart" alone does
 * not say WHICH chart when seven timeframes are one keypress away.
 */
function IndexExportAction({ series }: { series: IndexSeries }) {
  const [state, setState] = useState<"idle" | "working" | "failed">("idle");
  const plan = buildIndexExport(series);
  const label = windowLabel(series.requested_window);
  const unavailable = plan === null;

  return (
    <div className="mt-2 flex items-center justify-end gap-3">
      {state === "failed" && (
        <span className="text-[12px] leading-relaxed text-text-muted" data-testid="index-export-error" role="status">
          The chart could not be saved. Please try again.
        </span>
      )}
      <button
        type="button"
        data-testid="index-export"
        aria-label={
          unavailable
            ? "Download chart — there is no published index history to save yet"
            : `Download the Card Pirate Index chart for ${label} as a PNG image`
        }
        title={unavailable ? "There is no published index history to save yet." : undefined}
        aria-disabled={unavailable || undefined}
        aria-busy={state === "working" || undefined}
        disabled={state === "working"}
        onClick={() => {
          // The guard the omitted `disabled` attribute would have provided.
          if (unavailable || plan === null) return;
          setState("working");
          // The fonts the page actually loaded, read off a live element -
          // next/font names are hashed, so the canvas cannot guess them.
          const fonts = resolveExportFonts(
            typeof document === "undefined" ? null : document.documentElement,
          );
          void downloadIndexExport(plan, { fonts }).then((ok) => {
            setState(ok ? "idle" : "failed");
          });
        }}
        className={`mono rounded-[4px] border border-border-muted px-2 py-1 text-[10px] font-medium uppercase tracking-wider text-text-muted transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 disabled:cursor-not-allowed ${
          unavailable
            ? "cursor-not-allowed opacity-[0.65]"
            : "hover:text-text-secondary"
        }`}
      >
        {state === "working" ? "Saving…" : "Download chart"}
      </button>
    </div>
  );
}

/** A placeholder the SHAPE of the loaded hero, so the page does not grow by
 * several hundred pixels the instant the first response lands. */
function IndexHeroSkeleton() {
  return (
    <div aria-busy="true" aria-live="polite" className="mt-4">
      <span className="sr-only">Loading the Card Pirate Index…</span>
      <div className="h-11 w-52 rounded bg-bg-elevated sm:h-14" />
      <div className="mt-4 grid grid-cols-3 gap-3 border-t border-border-muted pt-3 sm:max-w-md">
        {[0, 1, 2].map((i) => (
          <div key={i}>
            <div className="h-2 w-10 rounded bg-bg-elevated" />
            <div className="mt-2 h-4 w-16 rounded bg-bg-elevated" />
          </div>
        ))}
      </div>
      <div className="mt-5 h-[260px] w-full rounded-panel bg-bg-elevated sm:h-[340px] lg:h-[400px]" />
    </div>
  );
}
