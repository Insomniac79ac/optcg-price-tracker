import { apiGet } from "@/lib/api";
import { windowLabel } from "@/lib/cardPirateIndex";
import { formatJpy } from "@/lib/format";
import type { PrintSeries } from "@/lib/printSeries";

/** GET /prints/{id}/analytics - one exact print's HISTORICAL analytics.
 *
 * Everything this module models is read off rows Atlas already archived. The
 * endpoint recomputes nothing, and neither does anything here: there is no
 * function in this file that derives a headline figure, a change, a span or an
 * availability answer from the points it was handed. Each is carried from the
 * server field that decided it.
 *
 * WHY THIS IS NOT `printSeries.ts`. That module owns `/prints/{id}/series` and
 * its own 7d/30d/all grammar, which is unchanged and still shipped. This one
 * owns the seven-token analytics grammar. They share the `PrintSeries` shape
 * deliberately - the analytics response embeds the series payload verbatim,
 * built by the same server function - so the chart is fed from either without
 * a second DTO, and a break drawn under one grammar is drawn identically
 * under the other.
 */

/** One row of the server's `windows` map.
 *
 * Structurally the aggregate Index's `IndexWindowRow`, because it is built by
 * the same server function against the same grammar. `available` is a SPAN
 * test over every series this print has - not a point count and not a Market
 * Index test - so a print with a month of Yuyu-Tei history reports 1M
 * available even where the index itself is nine days old. */
export interface PrintAnalyticsWindowRow {
  token: string;
  available: boolean;
  covered_days: number;
  required_days: number | null;
}

/** Movement of the archived Market Index across the requested window.
 *
 * Published by the server ONLY where its two ends are comparable. A window
 * crossing an index_version bump, a source_semantics_version bump or a change
 * in which sources built the number yields no change at all - the parent's
 * `change_unavailable_reason` names which. Nothing here is ever recomputed
 * from the chart's points: a naive first-vs-last would report a methodology
 * change as a price change, which is exactly what the server refuses to do. */
export interface PrintAnalyticsChange {
  absolute_jpy: number;
  pct: number;
  from_date: string;
  to_date: string;
  /** A methodology boundary lies inside the window. True beside a published
   * change (the ends were still comparable) as well as on a refusal. */
  spans_break: boolean;
}

/** The Market Index headline for one print and one window.
 *
 * ARCHIVED, NOT LIVE. Every field is read from `market_index_snapshots`, so
 * `current_value_jpy` is the newest value Atlas WROTE DOWN and is stamped with
 * `current_as_of` for exactly that reason. The live index on `GET /prints/{id}`
 * is resolved at request time and is a different number that can legitimately
 * differ; the page renders it separately and labels it, rather than letting
 * either stand unqualified.
 *
 * `observed_days` IS DISTINCT DAYS CARRYING A USABLE ARCHIVED VALUE. It is not
 * sales, trades, volume, listings or a sample size, and no such figure exists
 * anywhere in Atlas to publish. There is deliberately no average price either -
 * the only combination rule the system owns is a same-day median across
 * sources, so a mean over time would be inventing methodology.
 *
 * Every value field is nullable because a print with no archived index has no
 * headline, and null is the honest answer rather than a zero. */
export interface PrintAnalyticsHeadline {
  current_value_jpy: number | null;
  current_as_of: string | null;
  starting_value_jpy: number | null;
  starting_as_of: string | null;
  low_value_jpy: number | null;
  low_as_of: string | null;
  high_value_jpy: number | null;
  high_as_of: string | null;
  change: PrintAnalyticsChange | null;
  change_unavailable_reason: string | null;
  observed_days: number;
  coverage_status: string | null;
}

/** One drawn series, summarised by the SERVER - see PrintSeriesStatsOut.
 *
 * THE WHOLE POINT IS THAT THE BROWSER COMPUTES NONE OF THIS. Every figure
 * below is an archived observation the server selected and, where a change is
 * published, arithmetic the server performed. A client that recomputed any of
 * it from the chart's points would disagree with the server the moment a point
 * was disqualified, a day carried a null, or the window's ends sat either side
 * of a methodology boundary - which is exactly when a reader most needs the
 * number to be right.
 *
 * ONE ROW PER SERIES THE CHART ACTUALLY DRAWS, and none at all for a platform
 * with nothing to show. `series_key` matches the `key` of the entry in
 * `series[]` it describes, so the two are joined without guessing - which is
 * how this row gets its display name without a second naming rule.
 *
 * `observed_days` IS DISTINCT DRAWABLE DAYS. Not observations, samples,
 * trades, sales or volume: Atlas records no transaction anywhere, so there is
 * no such figure to render and no wording here may imply one.
 */
export interface PrintSeriesStats {
  series_key: string;
  kind: "market_index" | "source";
  source: string | null;
  starting_value_jpy: number;
  starting_as_of: string;
  current_value_jpy: number;
  current_as_of: string;
  low_value_jpy: number;
  low_as_of: string;
  high_value_jpy: number;
  high_as_of: string;
  observed_days: number;
  /** The SAME shape as the headline's change - one renderer, one set of
   * rules. Null where the server declined to subtract. */
  change: PrintAnalyticsChange | null;
  /** Why there is no change, in the server's break vocabulary. Rendered
   * through `changeUnavailableCopy`; the raw token is never shown. */
  change_unavailable_reason: string | null;
}

export interface PrintAnalytics {
  card_print_id: number;
  /** Always echoes the token that was asked for. An unavailable window is
   * answered honestly with its own (possibly empty) data, never substituted
   * with another token's - so this is what the control presses. */
  requested_window: string;
  /** Null for `all`. */
  window_start: string | null;
  /** The server's opening view, and MARKET-INDEX-AUTHORITATIVE: it spans the
   * archived index alone, while `windows[].available` spans every series. A
   * long source-only history therefore makes 3M selectable while this stays
   * `all`. That pairing is intended and must not be "corrected" here. */
  default_window: string;
  generated_at: string;
  windows: PrintAnalyticsWindowRow[];
  headline: PrintAnalyticsHeadline;
  /** The `/prints/{id}/series` shape, unchanged. */
  series: PrintSeries[];
  /** Server-derived summaries of the series above, one per DRAWN series, in
   * the server's own order. Absent platforms simply have no row. */
  series_stats: PrintSeriesStats[];
}

/** Fetch one print's analytics.
 *
 * Omitting `window` is meaningful, not a convenience: it is how the client
 * asks the SERVER which window to open on. Passing `default_window` back on
 * the first request would be the client deciding, and would hide the case
 * where the server's default differs from what a stale client believes.
 *
 * A window change re-asks the server rather than slicing a payload already in
 * hand - the headline, the availability map and the series all belong to the
 * window that produced them, and a locally narrowed copy would disagree with
 * every one of them. */
export function fetchPrintAnalytics(
  printId: string | number,
  window?: string,
): Promise<PrintAnalytics> {
  return apiGet<PrintAnalytics>(`/prints/${printId}/analytics`, {
    params: window ? { window } : undefined,
  });
}

/** Which token the control shows as pressed.
 *
 * The server's echo, used as published. This only refuses a value outside the
 * grammar the server itself sent - which would otherwise leave the control
 * with no pressed button at all - and falls back to the FIRST window the
 * server published, never to a hardcoded token, so a grammar change is
 * followed rather than second-guessed.
 *
 * Deliberately NOT `default_window`: that is the opening policy, and pressing
 * it would light the wrong button on every subsequent selection. */
export function pressedAnalyticsWindow(analytics: PrintAnalytics): string {
  const offered = analytics.windows.map((row) => row.token);
  if (offered.includes(analytics.requested_window)) return analytics.requested_window;
  return offered[0] ?? analytics.requested_window;
}

/** Why an unreachable window is unreachable, in a sentence.
 *
 * Built from the server's own two numbers so the reason a control cannot be
 * pressed is the same fact that made it unpressable. Null for an available
 * window, and null when `required_days` is null (`all`, which has no
 * requirement to fall short of) - the caller drops the clause rather than
 * printing a sentence about a threshold that does not exist. */
export function windowShortfall(row: PrintAnalyticsWindowRow): string | null {
  if (row.available || row.required_days === null) return null;
  const days = row.covered_days === 1 ? "1 day" : `${row.covered_days} days`;
  return `Atlas has ${days} of history for this print; this window needs ${row.required_days}.`;
}

/** The server's `change_unavailable_reason` as a collector-facing sentence.
 *
 * WHY EVERY REASON GETS ITS OWN WORDING. These are not interchangeable
 * apologies. Two of them say Atlas changed how it measures and therefore
 * refuses to subtract across the boundary; one says the sources behind the
 * number changed; two say a SOURCE changed what it was quoting; the rest say
 * the window simply has nothing, or only one thing, to compare. Collapsing
 * them into "change unavailable" would throw away the only explanation the
 * reader has for why a chart with a visible slope reports no movement.
 *
 * WHO CHANGED WHAT IS THE DISTINCTION THAT MATTERS. The first three say ATLAS
 * changed - its own calculation, its own reading of source prices, its own set
 * of contributors - and they speak for the Market Index. The two series-break
 * reasons say THE SOURCE changed what it was quoting, and are the only refusals
 * a per-source row can carry. Wording them as Atlas changing something would
 * blame the wrong party for the boundary; wording them as a price change would
 * be worse.
 *
 * An unrecognised reason returns null rather than a guess: the server may name
 * a refusal this build has never heard of, and inventing prose for it would be
 * asserting a meaning we do not know. The caller renders the neutral line. */
export function changeUnavailableCopy(reason: string | null): string | null {
  switch (reason) {
    case "index_version_change":
      return "Atlas changed how the Market Index is calculated inside this window, so its two ends are not comparable.";
    case "source_semantics_version_change":
      return "Atlas changed how source prices are read inside this window, so its two ends are not comparable.";
    case "contributor_set_changed":
      return "Different sources built the Market Index at each end of this window, so the two are not comparable.";
    // The two SERIES break reasons, which reach here on a per-source row.
    // `reference_type_change` is the named case - Atlas knows the instrument on
    // both sides of the boundary - and `instrument_change` is the unlabelled
    // one, where the source changed instrument and Atlas has a name for
    // neither. Both are a real boundary and neither is a price movement, so
    // they read alike and differ only in how specific the server could be.
    case "reference_type_change":
      return "This source changed the type of price reference inside this window, so its two ends are not comparable.";
    case "instrument_change":
      return "This source changed the price instrument inside this window, so its two ends are not comparable.";
    case "no_archived_value_in_window":
      return "Atlas has no archived Market Index value in this window.";
    case "single_point_window":
      return "Only one day of archived Market Index falls in this window, so there is nothing to compare it with.";
    case "no_comparable_baseline":
      return "This window has no comparable starting value to measure movement from.";
    case "null_archived_value":
      return "An end of this window has no usable archived Market Index value.";
    case "non_positive_baseline":
      return "This window's starting value cannot be used to measure movement.";
    default:
      return null;
  }
}

/** The server's own absolute change, signed for display.
 *
 * ONE FORMATTER, THREE SURFACES. The archived headline, the per-series window
 * performance rows and the PNG export all print the same server field, and
 * three inline copies of "put a sign in front of the magnitude" is three
 * chances for one of them to render a fall as a rise. The sign comes from the
 * server's value; only its presentation happens here.
 *
 * A minus sign, not a hyphen: this is a number being read, not a token.
 */
export function formatSignedJpy(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "\u2212" : "";
  return `${sign}${formatJpy(Math.abs(value))}`;
}

/** The server's own percentage, signed and fixed to two places.
 *
 * A genuine 0 is formatted as `0.00%` and carries NO sign, because it is a
 * measurement - the series is where it started - and is a different statement
 * from "no comparable change", which has no percentage at all. */
export function formatSignedPct(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "\u2212" : "";
  return `${sign}${Math.abs(value).toFixed(2)}%`;
}

/** `coverage_status` as a short qualifier, or null where it adds nothing.
 *
 * Only `limited` is worded. `full` needs no caption - the ordinary case earns
 * no sentence - and `none` never reaches here because a headline with no
 * archived value renders its own empty state instead. Not a confidence,
 * quality or reliability measure: it is the server's own 1:1 relabelling of
 * how many sources stood behind the archived value. */
export function coverageQualifier(status: string | null): string | null {
  return status === "limited" ? "Built from a single source" : null;
}

/** A window token as a control label - the shared display forms.
 *
 * Re-exported from @/lib/cardPirateIndex rather than redefined: the aggregate
 * Card Pirate Index and one print's timeframe control publish the SAME seven
 * tokens from the same server function, and two independent label maps are how
 * "2W" here and "2w" there start to drift. */
export { windowLabel };
