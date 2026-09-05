/** `GET /prints/{print_id}/series` - the multi-platform price history behind
 * the print page's analytics chart.
 *
 * WHAT THIS MODULE IS FOR. One print, N platforms, one chart. Market Index and
 * each independent platform arrive as separate named series so a collector can
 * see them beside each other and tell them apart; nothing here merges them,
 * and nothing here reconstructs a series from `/prints/{id}/prices`.
 *
 * WHAT IT REFUSES TO DO.
 *
 *   It classifies nothing. Whether an observation is market evidence is
 *   `eligible`/`constraint` on the point itself, decided by
 *   app.services.source_semantics. There is no threshold, no ¥1,000 and no
 *   source name in any rule below - the same discipline @/lib/sourceConstraint
 *   and @/lib/printPriceHistory keep.
 *
 *   It segments nothing of its own INVENTION. Where a measurement changed -
 *   a source's instrument, the Market Index's algorithm or source-semantics
 *   version - the server says so, per segment and again in `breaks`, and this
 *   module carries that boundary through to the renderer untouched. The one
 *   split it adds is within a server segment, at points that are not market
 *   prices (a constrained reading, a day the index recorded no value), which
 *   is the same "never stroke through a disqualified observation" rule the
 *   single-source history has always had.
 *
 *   It never reads a stored `price_type`. The server deliberately withholds
 *   it (see schemas.PrintSeriesPointOut) precisely so no client can couple to
 *   collector-side storage names; the public vocabulary is
 *   `reference_type`/`evidence_type` per segment, and that is all this file
 *   knows.
 *
 *   It fabricates no value. A day with no observation has no point, and no
 *   point is ever forward-filled, interpolated into the data, or substituted
 *   with zero. An archived Market Index value that really was NULL - no source
 *   was eligible that day - is a recorded result, kept visible as such and
 *   never plotted as ¥0.
 *
 * A FUTURE SOURCE NEEDS NO CODE HERE. The request names no platforms, so the
 * server returns every source that has observed this print; an unrecognised
 * source falls through `sourceDisplayName` to its own name, and an
 * unrecognised instrument to a humanised form of the server's own token.
 */

import { apiGet } from "./api";
import { sourceDisplayName } from "./prints";
import { instrumentLabel } from "./sourceEvidence";

/** The three windows the backend offers. 90d is deliberately absent - it is
 * not implemented server-side (see app.services.print_series.WINDOW_DAYS), and
 * a control for it would be a promise this product cannot keep. */
export type PrintSeriesWindow = "7d" | "30d" | "all";

export const PRINT_SERIES_WINDOWS: PrintSeriesWindow[] = ["7d", "30d", "all"];

/** What the print page asks for on first paint. Matches the server's own
 * default, so the initial request and a re-request for 30D are the same. */
export const DEFAULT_PRINT_SERIES_WINDOW: PrintSeriesWindow = "30d";

export const WINDOW_LABEL: Record<PrintSeriesWindow, string> = {
  "7d": "7D",
  "30d": "30D",
  all: "All",
};

/** One normalised historical point - see schemas.PrintSeriesPointOut.
 *
 * One shape serves both series kinds and the fields that do not apply to a
 * kind are null, so nothing here has to branch on the parent before reading a
 * point. `value_jpy` is NEVER a stand-in for missing data: a day with no
 * observation has no point at all, and the only null value is an archived
 * index whose stored value really was null. */
export interface PrintSeriesPoint {
  /** The observation's own instant. Present for completeness; the chart plots
   * on `day`, because that is the grain the server normalised to and the grain
   * on which two platforms are comparable. */
  t: string;
  /** UTC calendar day, `YYYY-MM-DD`. */
  day: string;
  value_jpy: number | null;

  // --- source points ---
  reference_type?: string | null;
  evidence_type?: string | null;
  eligible?: boolean | null;
  constraint?: string | null;
  ineligible_reason?: string | null;
  sample_size?: number | null;
  observations_in_day?: number | null;

  // --- market_index points ---
  index_version?: number | null;
  source_semantics_version?: number | null;
  source_count?: number | null;
  coverage_status?: string | null;
  source_price_range_low_jpy?: number | null;
  source_price_range_high_jpy?: number | null;
}

/** A run of points measured the same way. A boundary between two of these is
 * an instrument or methodology change, never a price change. */
export interface PrintSeriesSegment {
  reference_type: string | null;
  evidence_type: string | null;
  index_version: number | null;
  source_semantics_version: number | null;
  points: PrintSeriesPoint[];
}

/** One boundary between segments, timestamped at the first point AFTER the
 * change. `reason` is `reference_type_change`, `instrument_change`,
 * `index_version_change` or `source_semantics_version_change`; which from_/to_
 * fields are populated depends on it. */
export interface PrintSeriesBreak {
  at: string;
  reason: string;
  from_reference_type?: string | null;
  to_reference_type?: string | null;
  from_index_version?: number | null;
  to_index_version?: number | null;
  from_source_semantics_version?: number | null;
  to_source_semantics_version?: number | null;
}

/** Measured facts about what a series holds - NOT a score. `covers_*` answer
 * historical span, and null means this window cannot answer the question.
 * Neither is a confidence, reliability or accuracy measure, and nothing in the
 * UI may render either as one. */
export interface PrintSeriesCoverage {
  earliest: string | null;
  latest: string | null;
  distinct_days: number;
  point_count: number;
  covers_7d: boolean | null;
  covers_30d: boolean | null;
}

export interface PrintSeries {
  /** The selector that produced this series - `market_index` or
   * `source:<name>`. Stable across windows, so it is the identity a chip
   * selection is remembered by. */
  key: string;
  kind: "market_index" | "source";
  source: string | null;
  /** `primary` for market-facing evidence, `auxiliary` for a value that is
   * reported but is not what the card costs. Only primary series are selected
   * by default; nothing is reachable as auxiliary today. */
  role: "primary" | "auxiliary";
  /** False in two honest ways, told apart by `unavailable_reason`:
   * `source_not_configured` (Atlas does not collect this platform) and
   * `no_history_in_window`. Neither is "the card has no price". */
  available: boolean;
  unavailable_reason: string | null;
  segments: PrintSeriesSegment[];
  breaks: PrintSeriesBreak[];
  coverage: PrintSeriesCoverage;
}

export interface PrintSeriesHistory {
  card_print_id: number;
  window: PrintSeriesWindow;
  /** Null for `all`, which returns the real available history and claims
   * nothing about its depth. */
  window_start: string | null;
  generated_at: string;
  series: PrintSeries[];
}

/** GET /prints/{id}/series.
 *
 * NAMES NO PLATFORMS. Omitting `series` is what makes the response
 * self-describing: the server answers with Market Index plus every source that
 * has actually observed THIS print, discovered from the data rather than from
 * a list of source names. A platform added to Atlas tomorrow therefore appears
 * in this chart the first time it records an observation, with no change here.
 *
 * The window IS sent, because changing it must re-ask the server rather than
 * slice a payload the client already holds - a 7D view filtered out of a 30D
 * response would silently disagree with the server's own coverage answers. */
export function fetchPrintSeries(
  printId: string | number,
  window: PrintSeriesWindow = DEFAULT_PRINT_SERIES_WINDOW,
): Promise<PrintSeriesHistory> {
  return apiGet<PrintSeriesHistory>(`/prints/${printId}/series`, {
    params: { window },
  });
}

/** A `reference_type` in a collector's words.
 *
 * Re-exported from @/lib/sourceEvidence rather than defined here: the chart's
 * chips, its legend and the evidence rows beneath it must all say "Current
 * listing" for the same server word, and one exported function is how that
 * stays true. See that module for the humanising fallback and the null rule. */
export { instrumentLabel };

/** The instrument a whole series is measured in, or null when it changed.
 *
 * A series whose segments disagree has no single instrument, and putting the
 * latest one in the legend would label historical points with a measurement
 * they were not taken under. The per-segment truth is still on screen - the
 * break marker and the tooltip both carry it - so the legend simply stops
 * claiming what it cannot. */
function agreedReferenceType(series: PrintSeries): string | null {
  const types = new Set(series.segments.map((segment) => segment.reference_type ?? ""));
  if (types.size !== 1) return null;
  const [only] = [...types];
  return only === "" ? null : only;
}

/** "Market Index", "Yuyu-Tei · Retail price", "SNKRDUNK · Current listing".
 *
 * Market Index is NEVER given a platform suffix and never appears as a source:
 * it is Atlas's own combination of the platforms beneath it, not a place a
 * card is quoted. A source keeps its own name from `sourceDisplayName`, so an
 * unknown platform is named rather than relabelled, and gains the instrument
 * suffix only where the server said what the instrument was. */
export function seriesDisplayLabel(series: PrintSeries): string {
  if (series.kind === "market_index") return "Market Index";
  const platform = sourceDisplayName(series.source ?? "");
  const instrument = instrumentLabel(agreedReferenceType(series));
  return instrument ? `${platform} · ${instrument}` : platform;
}

/** The platform half of a label - "Market Index", "Yuyu-Tei", "SNKRDUNK". */
export function seriesPlatformLabel(series: PrintSeries): string {
  if (series.kind === "market_index") return "Market Index";
  return sourceDisplayName(series.source ?? "");
}

/** The instrument half, or null when there is none to state.
 *
 * Null in three honest ways, all of which mean "this build cannot name one
 * instrument for this series": Market Index is not quoted in an instrument at
 * all, an unconfigured source has none named, and a series whose instrument
 * changed has more than one. Callers render the platform alone. */
export function seriesInstrumentLabel(series: PrintSeries): string | null {
  if (series.kind === "market_index") return null;
  return instrumentLabel(agreedReferenceType(series));
}

/** Whether a series is selected when the reader has expressed no preference:
 * Market Index and every PRIMARY source series that actually has history in
 * this window. An unavailable series is not a default because there is nothing
 * to draw, and an auxiliary value is not a default because it is not what the
 * card costs. */
export function isDefaultSelected(series: PrintSeries): boolean {
  return series.available && series.role === "primary";
}

/** The series a reader can actually act on.
 *
 * An unavailable series is dropped entirely rather than offered as a disabled
 * chip: `source_not_configured` and `no_history_in_window` are both real
 * answers, but neither gives the reader anything to toggle, and a dead control
 * beside three live ones reads as a platform that is broken rather than one
 * that is quiet. */
export function selectableSeries(history: PrintSeriesHistory | null): PrintSeries[] {
  if (!history) return [];
  return history.series.filter((series) => series.available && series.segments.length > 0);
}

/** Whether a point can be drawn as a market price.
 *
 * Two ways it cannot, and neither is missing data:
 *   - `value_jpy === null` - an archived Market Index day on which no source
 *     was eligible. A recorded result, and never a zero.
 *   - `eligible === false` - source semantics disqualified the reading (a
 *     platform-minimum listing, say). The number is real and stays available
 *     to the tooltip; it is not a price this card traded at.
 *
 * An ABSENT `eligible` reads as plottable: an API that never classified a
 * point has not disqualified it, the same reading @/lib/printPriceHistory
 * takes. */
function isPlottable(point: PrintSeriesPoint): boolean {
  return point.value_jpy !== null && point.eligible !== false;
}

/** One continuous line. Never spans a server segment, and never crosses a
 * point that is not a market price. */
export interface SeriesStroke {
  /** The Recharts `dataKey`. Unique per stroke, which is the entire mechanism
   * behind "nothing is joined across a break": two strokes are two <Line>s
   * with two key spaces, so there is no path between them to draw. */
  dataKey: string;
  seriesKey: string;
  segmentIndex: number;
  /** The instrument THIS stroke was measured in, where the server named one. */
  instrument: string | null;
  points: PrintSeriesPoint[];
}

/** What the tooltip says about one series on one day. */
export interface SeriesPointDetail {
  seriesKey: string;
  label: string;
  kind: "market_index" | "source";
  valueJpy: number | null;
  /** False for a constrained reading or a null archived index - shown, but
   * never as a price on the line. */
  plotted: boolean;
  constraint: string | null;
  coverageStatus: string | null;
}

export interface SeriesChartRow {
  /** Epoch milliseconds at the start of the UTC day. */
  t: number;
  day: string;
  detail: SeriesPointDetail[];
  [dataKey: string]: number | string | SeriesPointDetail[] | undefined;
}

/** A break the reader can be shown, positioned on the chart's own day grid. */
export interface SeriesBreakMarker {
  seriesKey: string;
  t: number;
  reason: string;
}

export interface SeriesChartModel {
  /** The selected series, in the server's order, each with its strokes. */
  series: {
    key: string;
    kind: "market_index" | "source";
    source: string | null;
    label: string;
    strokes: SeriesStroke[];
    /** Every point of this series in the window, plotted or not. */
    pointCount: number;
    /** Points this chart can draw. Zero means the series is present but has
     * nothing on the line - a wholly constrained platform, say. */
    plottedCount: number;
  }[];
  rows: SeriesChartRow[];
  breaks: SeriesBreakMarker[];
  /** True when at least one stroke has two or more points, i.e. there is a
   * line to draw rather than a scatter of single observations. */
  hasLine: boolean;
  /** True when anything at all can be marked on the chart. */
  hasPoints: boolean;
}

/** The order the lines are PAINTED in - not the order anything is read in.
 *
 * The Market Index is Atlas's combination of the platforms beneath it, so on
 * any print with a single eligible source it holds exactly that source's value
 * and the two series occupy identical pixels. Painted in the server's order
 * the index goes down first and the source paints over it, which leaves a lit
 * gold chip and no gold anywhere on the plot.
 *
 * So the index is drawn LAST, and (at the call site) narrower, which leaves
 * the platform beneath it showing as a halo either side: agreement reads as a
 * gold core inside a coloured edge. Nothing is displaced and no point is moved
 * off its real value - the fix is entirely in paint order and stroke width.
 *
 * The legend, the tooltip and the colour assignment all still use the server's
 * own order, so this changes what is visible, never what anything is called.
 */
export function seriesPaintOrder<T extends { kind: "market_index" | "source" }>(
  series: readonly T[],
): T[] {
  return [
    ...series.filter((entry) => entry.kind !== "market_index"),
    ...series.filter((entry) => entry.kind === "market_index"),
  ];
}

/** Epoch milliseconds for a `YYYY-MM-DD` UTC day. */
export function dayToTime(day: string): number {
  return Date.parse(`${day}T00:00:00Z`);
}

/** A chart date, rendered in UTC.
 *
 * The server's grain is the UTC calendar day, so formatting it in the
 * reader's local zone would relabel a whole series by a day for anyone west
 * of Greenwich - and put the tooltip's date one off from the axis tick beside
 * it. */
export function formatSeriesDay(day: string): string {
  const parsed = new Date(dayToTime(day));
  if (Number.isNaN(parsed.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeZone: "UTC" }).format(parsed);
}

export function strokeDataKey(seriesKey: string, segmentIndex: number, strokeIndex: number): string {
  return `${seriesKey}__s${segmentIndex}_${strokeIndex}`;
}

/** Split one server segment into drawable strokes.
 *
 * A non-plottable point ENDS the run in progress; the next plottable one opens
 * a new run. Leading and trailing non-plottable points therefore open nothing,
 * so a segment that is entirely constrained yields no stroke at all. */
function strokesForSegment(
  seriesKey: string,
  segment: PrintSeriesSegment,
  segmentIndex: number,
): SeriesStroke[] {
  const strokes: SeriesStroke[] = [];
  let current: PrintSeriesPoint[] = [];

  const flush = () => {
    if (current.length === 0) return;
    strokes.push({
      dataKey: strokeDataKey(seriesKey, segmentIndex, strokes.length),
      seriesKey,
      segmentIndex,
      instrument: instrumentLabel(segment.reference_type),
      points: current,
    });
    current = [];
  };

  for (const point of segment.points) {
    if (isPlottable(point)) current.push(point);
    else flush();
  }
  flush();
  return strokes;
}

/** Build everything the chart renders, for exactly the selected series.
 *
 * `selected` is a set of series keys. A key naming a series the response does
 * not carry is ignored rather than invented, which is what lets a chip
 * selection survive a window change that dropped a platform.
 */
export function buildSeriesChartModel(
  history: PrintSeriesHistory | null,
  selected: ReadonlySet<string>,
): SeriesChartModel {
  const empty: SeriesChartModel = {
    series: [],
    rows: [],
    breaks: [],
    hasLine: false,
    hasPoints: false,
  };
  if (!history) return empty;

  const chosen = history.series.filter(
    (series) => series.available && selected.has(series.key),
  );
  if (chosen.length === 0) return empty;

  const rowsByTime = new Map<number, SeriesChartRow>();
  const rowFor = (day: string): SeriesChartRow => {
    const t = dayToTime(day);
    const existing = rowsByTime.get(t);
    if (existing) return existing;
    const created: SeriesChartRow = { t, day, detail: [] };
    rowsByTime.set(t, created);
    return created;
  };

  const modelSeries: SeriesChartModel["series"] = [];
  const breaks: SeriesBreakMarker[] = [];

  for (const series of chosen) {
    const label = seriesDisplayLabel(series);
    const strokes = series.segments.flatMap((segment, index) =>
      strokesForSegment(series.key, segment, index),
    );

    let pointCount = 0;
    let plottedCount = 0;
    for (const segment of series.segments) {
      for (const point of segment.points) {
        pointCount += 1;
        const plotted = isPlottable(point);
        if (plotted) plottedCount += 1;
        rowFor(point.day).detail.push({
          seriesKey: series.key,
          label,
          kind: series.kind,
          valueJpy: point.value_jpy,
          plotted,
          constraint: point.constraint ?? null,
          coverageStatus: point.coverage_status ?? null,
        });
      }
    }

    for (const stroke of strokes) {
      for (const point of stroke.points) {
        // A null cannot reach here - isPlottable already excluded it - but the
        // narrowing keeps the row's value type honest rather than asserting.
        if (point.value_jpy === null) continue;
        rowFor(point.day)[stroke.dataKey] = point.value_jpy;
      }
    }

    for (const entry of series.breaks) {
      const day = entry.at.slice(0, 10);
      const t = dayToTime(day);
      if (Number.isNaN(t)) continue;
      breaks.push({ seriesKey: series.key, t, reason: entry.reason });
    }

    modelSeries.push({
      key: series.key,
      kind: series.kind,
      source: series.source,
      label,
      strokes,
      pointCount,
      plottedCount,
    });
  }

  const rows = [...rowsByTime.values()].sort((a, b) => a.t - b.t);
  for (const row of rows) {
    row.detail.sort((a, b) => a.label.localeCompare(b.label));
  }

  return {
    series: modelSeries,
    rows,
    breaks,
    hasLine: modelSeries.some((entry) =>
      entry.strokes.some((stroke) => stroke.points.length >= 2),
    ),
    hasPoints: modelSeries.some((entry) => entry.plottedCount > 0),
  };
}
