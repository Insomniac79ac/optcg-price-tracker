/** Turns one print's `GET /prints/{id}/prices` payload into the shapes the
 * "Price history" section renders, and decides - once, here - which of the
 * three honest presentations each source series has earned.
 *
 * WHAT THIS MODULE REFUSES TO DO. It never classifies an observation. Whether
 * a price means what its number says is `constraint`/`eligible` on the
 * observation itself, decided by app.services.source_semantics; there is no
 * threshold, no source name and no ¥1,000 anywhere below. A second opinion in
 * the browser is exactly how the two would drift apart - the same reasoning
 * that keeps @/lib/sourceConstraint free of platform minimums. It likewise
 * computes no percentage change: every trend number comes from the backend's
 * own `series` entries, which is why `changes` only ever *filters* them.
 *
 * The three presentations, and why a series gets each one:
 *
 *   plotted     - eligible observations on at least two distinct dates. Only
 *                 here is a line drawn, because only here is there movement
 *                 to show.
 *   compact     - eligible observations exist, but on a single date. One
 *                 price and its date, no trend line: a chart through one day
 *                 would be a shape invented from a single point.
 *   constrained - no eligible observation at all. The source reported, and
 *                 what it reported is not market evidence, so the series is
 *                 explained rather than drawn. The raw values are still
 *                 counted and surfaced - never hidden, never plotted.
 *
 * A series with no observations at all does not reach any of these: it is
 * dropped, because a source that never reported is not a fact about the card.
 */

import {
  sourceDisplayName,
  type PrintPriceHistory,
  type PrintPriceObservation,
  type PrintPriceSeriesTrend,
} from "./prints";

/** One eligible observation, ready for an axis. */
export interface PriceHistoryPoint {
  observationId: number;
  observedAt: string;
  /** Epoch milliseconds - the chart's x value, so points are spaced by real
   * elapsed time rather than by array index. */
  t: number;
  priceJpy: number;
}

/** A run of eligible observations with nothing disqualified between them.
 *
 * Segments are what stop a line being drawn *through* a constrained
 * observation. Two eligible prices either side of a platform-minimum reading
 * are not a continuous price movement - the source stopped reporting market
 * evidence in between - so they land in different segments and are stroked as
 * separate lines. */
export interface PriceHistorySegment {
  points: PriceHistoryPoint[];
}

export type PriceHistoryMode = "plotted" | "compact" | "constrained";

export interface PriceHistoryChange {
  /** "24h" / "7d" / "30d". */
  label: string;
  pct: number;
}

export interface PriceHistorySeriesView {
  /** Stable per (source, price_type) - used for React keys and chart dataKeys. */
  key: string;
  source: string;
  priceType: string;
  /** Collector-facing name, e.g. "Yuyu-Tei sell", "SNKRDUNK listing floor". */
  label: string;
  mode: PriceHistoryMode;
  /** Every eligible observation, oldest first. Empty for a constrained series. */
  points: PriceHistoryPoint[];
  /** `points`, split wherever a disqualified observation interrupted them. */
  segments: PriceHistorySegment[];
  /** How many distinct calendar dates carry an eligible observation - the
   * quantity the plotted/compact decision is made on. */
  distinctDateCount: number;
  /** The newest eligible observation, or null for a constrained series. */
  latest: PriceHistoryPoint | null;
  /** How many observations this source reported that source semantics
   * disqualified. Always surfaced, never plotted. */
  constrainedCount: number;
  /** The constraint name behind those, when they all agree on one - the
   * lookup key for @/lib/sourceConstraint's copy. Null when they disagree or
   * when the API sent no constraint name with them. */
  constraint: string | null;
  /** The newest disqualified raw value, so a constrained series can still
   * show the number the source actually reported. */
  constrainedLatestJpy: number | null;
  constrainedLatestAt: string | null;
  /** The OLDEST disqualified observation's timestamp. With
   * `constrainedLatestAt` it gives the span over which this source has been
   * reporting nothing but a constrained value - which is the one thing the
   * history section knows that the Market Index source panel above it does
   * not, and the reason a constrained row is worth rendering at all rather
   * than restating the panel's number. */
  constrainedFirstAt: string | null;
  /** Backend change values that are actually present. Never fabricated,
   * never defaulted to 0, and empty for a constrained series. */
  changes: PriceHistoryChange[];
}

export interface PriceHistoryView {
  cardPrintId: number;
  series: PriceHistorySeriesView[];
  /** True when at least one series earned a line - i.e. the section has a
   * chart to draw at all. */
  hasChart: boolean;
}

/** Stored `price_type` values, in a collector's words.
 *
 * Keyed on what the collector actually stores - SNKRDUNK writes `"floor"`,
 * not the API-facing `"listing_floor"` that appears only on a Market Index
 * `reference_type` (see services/api/app/services/source_semantics.py, "Stored
 * vs API-facing names"). An unrecognised type falls through to its own token
 * with underscores opened up, rather than being guessed at or dropped. */
const PRICE_TYPE_LABEL: Record<string, string> = {
  floor: "listing floor",
  sell: "sell",
  retail_sell: "retail sell",
  dealer_buy: "dealer buy",
  transaction_median: "median sold",
};

export function priceTypeLabel(priceType: string): string {
  return PRICE_TYPE_LABEL[priceType] ?? priceType.replace(/_/g, " ");
}

/** "Yuyu-Tei sell", "SNKRDUNK listing floor" - the source panels' own name for
 * the source, plus what kind of price this series is. Two series from one
 * source stay distinguishable, and a source is never renamed here. */
export function seriesLabel(source: string, priceType: string): string {
  return `${sourceDisplayName(source)} ${priceTypeLabel(priceType)}`;
}

export function seriesKey(source: string, priceType: string): string {
  return `${source}:${priceType}`;
}

/** The API's word on whether source semantics disqualified an observation.
 *
 * Absent reads as eligible: an API that predates the field never classified
 * the row, and "unclassified" is not "disqualified". Nothing here inspects
 * the price. */
function isEligible(observation: PrintPriceObservation): boolean {
  return observation.eligible !== false;
}

function toPoint(observation: PrintPriceObservation): PriceHistoryPoint {
  return {
    observationId: observation.id,
    observedAt: observation.observed_at,
    t: new Date(observation.observed_at).getTime(),
    priceJpy: observation.price_jpy,
  };
}

/** The backend's change values for one series, with the absent ones dropped.
 *
 * A null window means the backend found no observation at or before that
 * cutoff and declined to invent one; it is omitted rather than shown as 0%,
 * because "unchanged" and "unknown" are different facts about a card. A
 * genuine 0 IS reported - it is a measurement, not a gap. */
function changesFrom(trend: PrintPriceSeriesTrend | undefined): PriceHistoryChange[] {
  if (!trend) return [];
  const windows: [string, number | null][] = [
    ["24h", trend.change_24h_pct],
    ["7d", trend.change_7d_pct],
    ["30d", trend.change_30d_pct],
  ];
  return windows
    .filter((entry): entry is [string, number] => entry[1] !== null && entry[1] !== undefined)
    .map(([label, pct]) => ({ label, pct }));
}

/** Splits a series' observations into runs of eligible points, breaking the
 * run wherever a disqualified observation sits between them.
 *
 * `observations` must already be this series' own rows in chronological
 * order. Leading and trailing disqualified rows simply never open a segment,
 * so a wholly constrained series yields none. */
function buildSegments(observations: PrintPriceObservation[]): PriceHistorySegment[] {
  const segments: PriceHistorySegment[] = [];
  let current: PriceHistoryPoint[] = [];

  for (const observation of observations) {
    if (isEligible(observation)) {
      current.push(toPoint(observation));
      continue;
    }
    // A disqualified reading ends the run in progress. The next eligible
    // observation starts a new one, so nothing is stroked across the gap.
    if (current.length > 0) {
      segments.push({ points: current });
      current = [];
    }
  }
  if (current.length > 0) segments.push({ points: current });
  return segments;
}

/** The one constraint name behind a series' disqualified observations, or
 * null when they do not agree on one (or carry none). Used only to look up
 * existing collector copy - never rendered raw. */
function agreedConstraint(disqualified: PrintPriceObservation[]): string | null {
  const names = new Set(
    disqualified.map((observation) => observation.constraint ?? "").filter((name) => name !== ""),
  );
  if (names.size !== 1) return null;
  return [...names][0];
}

/** Build the whole section's view model.
 *
 * `cardPrintId` is the print whose page this is, and every observation is
 * checked against it. The endpoint is already scoped server-side, so this
 * filter should never remove anything - it exists so that a future response
 * shape, a cached body from another print, or a merged sibling payload cannot
 * put another printing's price on this page. Exact-print identity is the one
 * invariant this product does not infer (see lib/prints.ts).
 */
export function buildPriceHistoryView(
  history: PrintPriceHistory,
  cardPrintId: number,
): PriceHistoryView {
  const trendByKey = new Map(
    history.series.map((trend) => [seriesKey(trend.source, trend.price_type), trend]),
  );

  const grouped = new Map<string, PrintPriceObservation[]>();
  for (const observation of history.observations) {
    if (observation.card_print_id !== cardPrintId) continue;
    const key = seriesKey(observation.source, observation.price_type);
    const bucket = grouped.get(key);
    if (bucket) bucket.push(observation);
    else grouped.set(key, [observation]);
  }

  const series: PriceHistorySeriesView[] = [];
  for (const [key, rows] of grouped) {
    // The endpoint already returns observations oldest-first, but the
    // segment/latest logic is only correct on a sorted run and this is cheap
    // insurance against ever depending on that silently.
    const ordered = [...rows].sort(
      (a, b) => new Date(a.observed_at).getTime() - new Date(b.observed_at).getTime(),
    );
    const eligible = ordered.filter(isEligible);
    const disqualified = ordered.filter((observation) => !isEligible(observation));
    const points = eligible.map(toPoint);
    const distinctDateCount = new Set(eligible.map((o) => o.observed_at.slice(0, 10))).size;

    const mode: PriceHistoryMode =
      points.length === 0 ? "constrained" : distinctDateCount >= 2 ? "plotted" : "compact";

    const newestDisqualified = disqualified.length > 0 ? disqualified[disqualified.length - 1] : null;

    series.push({
      key,
      source: ordered[0].source,
      priceType: ordered[0].price_type,
      label: seriesLabel(ordered[0].source, ordered[0].price_type),
      mode,
      points,
      segments: mode === "plotted" ? buildSegments(ordered) : [],
      distinctDateCount,
      latest: points.length > 0 ? points[points.length - 1] : null,
      constrainedCount: disqualified.length,
      constraint: agreedConstraint(disqualified),
      constrainedLatestJpy: newestDisqualified?.price_jpy ?? null,
      constrainedLatestAt: newestDisqualified?.observed_at ?? null,
      constrainedFirstAt: disqualified.length > 0 ? disqualified[0].observed_at : null,
      // A series with nothing eligible has no market movement to report, so
      // its backend change values - computed across the raw stored prices,
      // constrained ones included - would describe something that is not a
      // market price. The constraint explanation stands in their place.
      changes: mode === "constrained" ? [] : changesFrom(trendByKey.get(key)),
    });
  }

  // Stable, source-name ordering so two visits to a print never reorder the
  // legend under the reader.
  series.sort((a, b) => a.label.localeCompare(b.label));

  return {
    cardPrintId,
    series,
    hasChart: series.some((entry) => entry.mode === "plotted"),
  };
}

/** One row per distinct timestamp across every plotted segment, with each
 * segment's price under its own key.
 *
 * Recharts takes a single data array for the whole chart, so every series
 * shares these rows and simply has no value at a timestamp it did not
 * observe. Each SEGMENT gets its own key (`series:type__s0`, `__s1`, ...)
 * rather than each series, which is what keeps a line from being stroked
 * across a constrained gap: the segments are different lines, so there is
 * nothing to join. Within one segment, absent timestamps are the other
 * source's observations and are connected across (`connectNulls`), because
 * the series genuinely did continue over them.
 */
export function segmentDataKey(seriesKeyValue: string, segmentIndex: number): string {
  return `${seriesKeyValue}__s${segmentIndex}`;
}

export type PriceHistoryChartRow = { t: number } & Record<string, number | undefined>;

export function buildChartRows(series: PriceHistorySeriesView[]): PriceHistoryChartRow[] {
  const byTimestamp = new Map<number, PriceHistoryChartRow>();

  for (const entry of series) {
    if (entry.mode !== "plotted") continue;
    entry.segments.forEach((segment, index) => {
      const key = segmentDataKey(entry.key, index);
      for (const point of segment.points) {
        const row = byTimestamp.get(point.t) ?? { t: point.t };
        row[key] = point.priceJpy;
        byTimestamp.set(point.t, row);
      }
    });
  }

  return [...byTimestamp.values()].sort((a, b) => a.t - b.t);
}
