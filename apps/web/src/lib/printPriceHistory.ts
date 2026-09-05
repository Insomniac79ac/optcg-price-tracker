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
 * IT NO LONGER DRAWS ANYTHING. The section's chart is built by
 * @/lib/printSeries from `GET /prints/{id}/series`, where the server owns
 * segmentation, instrument breaks and index-methodology breaks. Two
 * segmentation authorities is exactly how a line eventually gets stroked
 * across a boundary one of them knew about and the other did not, so this
 * module keeps only what it is still the authority on: the per-source EVIDENCE
 * ROWS beneath the chart, and the backend trend values in them.
 *
 * The three presentations, and why a series gets each one:
 *
 *   plotted     - eligible observations on at least two distinct dates, so
 *                 the backend's change windows describe real movement and the
 *                 row reports them.
 *   compact     - eligible observations exist, but on a single date. One
 *                 price and its date, and no trend: a change computed across
 *                 one day would be a shape invented from a single point.
 *   constrained - no eligible observation at all. The source reported, and
 *                 what it reported is not market evidence, so the series is
 *                 explained rather than measured. The raw values are still
 *                 counted and surfaced - never hidden, never plotted.
 *
 * A series with no observations at all does not reach any of these: it is
 * dropped, because a source that never reported is not a fact about the card.
 *
 * IT NAMES NO INSTRUMENT EITHER. A row is called "Yuyu-Tei · Retail price"
 * because the SERVER said that observation's `reference_type` is
 * `retail_sell`, not because anything here knows what the stored `price_type`
 * `"sell"` means. There is no price_type -> reference_type table below, and
 * adding one would recreate the drift this module was already written to
 * avoid: `price_type` is storage identity in a collector's own spelling, and
 * a browser that decodes it becomes a second naming authority that disagrees
 * with the server the moment a Card Rush / Mercado / Cardmarket source ships.
 * Stored price_types are used here for GROUPING and KEYS only - equality and
 * concatenation, never interpretation - so a token this build has never seen
 * segments correctly and is labelled by whatever the server calls it.
 */

import {
  sourceDisplayName,
  type PrintPriceHistory,
  type PrintPriceObservation,
  type PrintPriceSeriesTrend,
} from "./prints";
import { instrumentLabel } from "./sourceEvidence";

/** One eligible observation. */
export interface PriceHistoryPoint {
  observationId: number;
  observedAt: string;
  priceJpy: number;
}

export type PriceHistoryMode = "plotted" | "compact" | "constrained";

export interface PriceHistoryChange {
  /** "24h" / "7d" / "30d". */
  label: string;
  pct: number;
}

export interface PriceHistorySeriesView {
  /** Stable per (source, price_type) - used for React keys. */
  key: string;
  source: string;
  /** The STORED name, kept because it is this row's identity - what grouped
   * these observations together and what looks their trend up. OPAQUE: never
   * rendered, never decoded, never branched on. `label` is what the collector
   * sees. */
  priceType: string;
  /** The server's `reference_type` for this series - `retail_sell`,
   * `listing_floor`, or a token a future backend introduces. Null when the
   * server named no instrument. This, not `priceType`, is what `label` is
   * built from, and the only field here a caller may pass to
   * @/lib/sourceEvidence. */
  referenceType: string | null;
  /** The server's `evidence_type` - "listing" or "transaction" - saying
   * whether this series is asking prices or completed trades. Null when the
   * server named no instrument. Carried for callers that need to distinguish
   * the two; nothing in this module reads it. */
  evidenceType: string | null;
  /** Collector-facing name, e.g. "Yuyu-Tei · Retail price",
   * "SNKRDUNK · Current listing" - the same words the chart's chips use.
   * A series with no server-named instrument is the platform alone. */
  label: string;
  mode: PriceHistoryMode;
  /** Every eligible observation, oldest first. Empty for a constrained series. */
  points: PriceHistoryPoint[];
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
}

/** "Yuyu-Tei · Retail price", "SNKRDUNK · Current listing" - the source
 * panels' own name for the source, then what kind of price this series is, in
 * the SAME words and the same shape the chart's chips use. Two series from one
 * source stay distinguishable, and a source is never renamed here.
 *
 * THE INSTRUMENT ARGUMENT IS THE SERVER'S `reference_type`, NEVER A STORED
 * `price_type`. There is no table in this file turning `"floor"` into
 * `listing_floor` or `"sell"` into `retail_sell`, and there must not be: a
 * stored price_type is the collector's own spelling for a row, and a browser
 * that decodes it is a second naming authority which will disagree with the
 * server the day a Card Rush or Cardmarket source ships. The server already
 * resolves the instrument (app.services.source_instruments) and sends it on
 * every observation; this function only formats it.
 *
 * A series the server named no instrument for is the SOURCE ALONE -
 * "Cardmarket", not "Cardmarket · shop asking". That is the honest rendering
 * of a future source: its prices, its platform, and no claim about what the
 * number measures. */
export function seriesLabel(source: string, referenceType: string | null): string {
  const platform = sourceDisplayName(source);
  const instrument = instrumentLabel(referenceType);
  return instrument ? `${platform} · ${instrument}` : platform;
}

/** Identity, not meaning. `price_type` is opaque here - it is only ever
 * compared for equality and concatenated, never read for what it says - which
 * is exactly what keeps two instruments from one source (Yuyu-Tei's sell and
 * buy) in separate rows without this module knowing what either word means. */
export function seriesKey(source: string, priceType: string): string {
  return `${source}:${priceType}`;
}

/** The one `reference_type` a group's observations agree on, or null.
 *
 * A group is one (source, price_type) so the server's answer is normally
 * constant across it; this is the same "disagreement has no single name" rule
 * @/lib/printSeries applies across segments, and it is deliberately generic -
 * whatever the tokens are, agreement is agreement. */
function agreedReferenceType(rows: PrintPriceObservation[]): string | null {
  const types = new Set(rows.map((row) => row.reference_type ?? ""));
  if (types.size !== 1) return null;
  const [only] = [...types];
  return only === "" ? null : only;
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
    const referenceType = agreedReferenceType(ordered);

    series.push({
      key,
      source: ordered[0].source,
      priceType: ordered[0].price_type,
      referenceType,
      evidenceType: ordered[0].evidence_type ?? null,
      label: seriesLabel(ordered[0].source, referenceType),
      mode,
      points,
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
  };
}
