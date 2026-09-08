/** The Card Pirate Index, as the browser sees it.
 *
 * WHAT THIS MODULE IS NOT ALLOWED TO DO. It derives no index number. Not one.
 * The level for a day, the change across a window, the period high and low,
 * and whether a window is covered are all decided by
 * `app.services.card_pirate_index_read` and arrive here already decided. The
 * backend's own docstring makes the point this file has to honour: the read
 * path "runs no estimator", because a read-time recomputation would let a
 * later change to the cap or to MIN_CONSTITUENTS silently rewrite a number a
 * collector already screenshotted. A client that recomputes a change from
 * `points[]` reintroduces exactly that, one layer further out.
 *
 * So: `change.absolute` and `change.pct` are rendered as received. `points[]`
 * is plotted in the order it arrives. Nothing is forward-filled, interpolated,
 * padded, re-sorted or summed. The only arithmetic below is presentational -
 * turning a decimal string into a formatted one, and choosing an axis domain -
 * and each of those is marked.
 *
 * WHAT THE SERVER NOW PUBLISHES, and what this module therefore does not
 * decide. Methodology sections 12.1/13.1/13.4 make the SERVER the authority
 * for three things this file used to infer, and TASK INDEX 2A-B moved all
 * three back:
 *
 *   `windows`         which tokens exist, and whether each is available. A
 *                     span test (section 12.2 rule 4), decided on the server.
 *                     This module no longer owns a hardcoded token list for
 *                     rendering - `INDEX_WINDOWS` remains only as the wire
 *                     vocabulary a response is validated against.
 *   `default_window`  section 13.1's ladder. The old "request 3m, read
 *                     `covers_requested_window`, fall back to `all`" probe is
 *                     GONE - it worked, but it made the client re-implement a
 *                     rule the document freezes on the server, and it cost an
 *                     extra request on every first paint.
 *   `breaks`          where the measurement changed, read off the persisted
 *                     rows' own version and cadence columns. Never derived
 *                     here from levels, dates or chart geometry.
 *
 * `splitRuns` still exists and still splits on `step_days`, because a
 * `snapshot_gap` is published as a break AND as a per-point fact; the split is
 * a rendering consequence of the server's own number, not an inference about
 * whether a gap occurred.
 */

import { apiGet } from "./api";

/** The published window grammar - methodology section 12, and the exact key
 * set of `WINDOW_DAYS` in app/services/card_pirate_index_read.py.
 *
 * NOT what the control is built from any more. The server publishes its own
 * ordered `windows` list and the UI renders that, so a token added there
 * appears without a frontend release. This list survives as the WIRE
 * VOCABULARY: it is what an incoming token is checked against before being
 * used as a key, and what a hand-typed request would be validated by. Sending
 * anything outside it earns a 400 that names the grammar back. */
export const INDEX_WINDOWS = ["2w", "1m", "3m", "6m", "1y", "2y", "all"] as const;

export type IndexWindow = (typeof INDEX_WINDOWS)[number];

export const INDEX_WINDOW_LABEL: Record<IndexWindow, string> = {
  "2w": "2W",
  "1m": "1M",
  "3m": "3M",
  "6m": "6M",
  "1y": "1Y",
  "2y": "2Y",
  all: "All",
};

/** The same seven windows as prose, for sentences rather than buttons.
 *
 * A control's label is shorthand a reader decodes because it sits in a row of
 * six others; the same token dropped into a sentence ("not recording for a
 * full 2W yet") is internal spelling leaking into copy. `all` has no entry
 * because it is not a duration - see IndexFootnotes for what happens instead
 * of wording it. */
export const INDEX_WINDOW_PROSE: Record<Exclude<IndexWindow, "all">, string> = {
  "2w": "two weeks",
  "1m": "a month",
  "3m": "three months",
  "6m": "six months",
  "1y": "a year",
  "2y": "two years",
};

export function isIndexWindow(value: string): value is IndexWindow {
  return (INDEX_WINDOWS as readonly string[]).includes(value);
}

/** A server token as a control label.
 *
 * The labels above are the frozen display forms and are used whenever the
 * token is one this build knows. A token it does not know is shown UPPERCASED
 * rather than hidden: the server published it, so it is a real window, and a
 * control that silently dropped it would be quietly overriding the authority
 * this whole tranche moved to the server. */
export function windowLabel(token: string): string {
  return isIndexWindow(token) ? INDEX_WINDOW_LABEL[token] : token.toUpperCase();
}

/** A server token as prose, or null when it has no sentence form.
 *
 * Null for `all` because it is not a duration, and null for an unknown token
 * because inventing a wording for one would be guessing at its meaning. The
 * caller drops the clause rather than printing a token mid-sentence. */
export function windowProse(token: string): string | null {
  if (!isIndexWindow(token) || token === "all") return null;
  return INDEX_WINDOW_PROSE[token];
}

/** One published point - see schemas.CardPirateIndexPointOut.
 *
 * Decimals arrive as strings and are KEPT as strings. Parsing them at the
 * boundary would put a float in the type where the server put an exact value,
 * and the one place a number is genuinely needed (the chart) converts there
 * and says so. */
export interface IndexPoint {
  date: string;
  value: string;
  is_base: boolean;
  prior_point_date: string | null;
  step_days: number | null;
  chain_link_log_return: string | null;
  constituent_count: number;
  eligible_print_count: number;
  movers_up: number | null;
  movers_down: number | null;
  movers_flat: number | null;
  capped_count: number | null;
}

/** Change between two PUBLISHED endpoints - see CardPirateIndexChangeOut.
 *
 * `spans_break` is not a warning that the number is wrong. It says the span
 * crosses a methodology boundary, so the figure is a linked-index return
 * rather than a claim that the underlying per-print measurements were
 * comparable across it. Suppressing it would be as dishonest as printing it
 * unqualified (section 13.2), so the UI shows it with a marker. */
export interface IndexChange {
  absolute: string;
  pct: string;
  from_date: string;
  to_date: string;
  spans_break: boolean;
}

/** One row of the server's `windows` list - see CardPirateIndexWindowOut.
 *
 * `available` is the server's span test (section 12.2 rule 4): the history
 * must reach back past the window's start. It is emphatically NOT "are there
 * enough points", and NOT anything this module may recompute from
 * `available_from` and a clock. Section 12.2 rule 3 calls this map "the key
 * affordance" precisely because it lets an unreachable timeframe render as a
 * disabled button with a reason rather than as a clickable path into a chart
 * that cannot answer it. */
export interface IndexWindowRow {
  token: string;
  available: boolean;
  covered_days: number;
  required_days: number | null;
}

/** One boundary in the returned series - see CardPirateIndexBreakOut.
 *
 * Every field is the server's. A version change is continuous (the level
 * carries across it, section 5.1 rule 4) and a `snapshot_gap` is missing data;
 * section 13.4 draws them differently, and `reason` is how the client knows
 * which it is holding without inspecting a single level. */
export interface IndexBreak {
  at: string;
  reason: string;
  from_methodology_version: number | null;
  to_methodology_version: number | null;
  from_index_version: number | null;
  to_index_version: number | null;
  from_source_semantics_version: number | null;
  to_source_semantics_version: number | null;
  carried: boolean | null;
  carried_level: string | null;
  carried_from_point_date: string | null;
  prior_point_date: string | null;
  step_days: number | null;
}

/** The three reasons that mean "the measurement changed here".
 *
 * A reason outside this set and not `snapshot_gap` is a server the client has
 * not been taught about yet. It is still MARKED, in neutral wording, rather
 * than dropped: a boundary nobody drew is a worse failure than one described
 * vaguely, and silently ignoring an unknown reason is how a client starts
 * showing a continuous line across a change it did not recognise. */
export const VERSION_BREAK_REASONS: ReadonlySet<string> = new Set([
  "methodology_version_change",
  "index_version_change",
  "source_semantics_version_change",
]);

export function isSnapshotGap(entry: IndexBreak): boolean {
  return entry.reason === "snapshot_gap";
}

export interface IndexSeries {
  scope_kind: string;
  scope_key: string;
  methodology_version: number;
  index_version: number | null;
  source_semantics_version: number | null;
  requested_window: string;
  window_start: string | null;
  available_from: string | null;
  available_to: string | null;
  covers_requested_window: boolean;
  points: IndexPoint[];
  starting_value: string | null;
  current_value: string | null;
  low_value: string | null;
  high_value: string | null;
  change: IndexChange | null;
  change_unavailable_reason: string | null;
  /** Section 12.1 server-authored metadata. The client RENDERS these; it does
   * not compute them, and it keeps no fallback that would let it quietly go
   * on deciding them itself if they were ever absent. */
  windows: IndexWindowRow[];
  default_window: string;
  breaks: IndexBreak[];
}

/** `string`, not `IndexWindow`, because the tokens the UI can request now come
 * from the server's own `windows` list. Narrowing to a locally-declared union
 * would make a token the server published un-requestable until this file was
 * edited - the exact coupling 2A-B removed. `INDEX_WINDOWS` is still what an
 * incoming value is validated against, at the point it is read. */
export function fetchIndexSeries(window: string): Promise<IndexSeries> {
  return apiGet<IndexSeries>("/analytics/index", { params: { window } });
}

/** The FIRST request, which names no window at all.
 *
 * There is no bootstrap constant any more, and its absence IS the contract.
 * Until TASK INDEX 2A-C this module exported `BOOTSTRAP_WINDOW = "all"`,
 * because the route's own `?window=` fallback was `3m` while the published
 * `default_window` was `all` - so asking for "the default" meant naming a
 * token, and this file had to know which one that was. The server now resolves
 * an absent window through section 13.1's ladder itself, so the client asks
 * for nothing and renders what comes back.
 *
 * That is what makes the 3M transition a server-side event: the day three
 * months of history exists, this same request starts returning `3m`, and
 * nothing here changes or needs to.
 */
export function fetchIndexDefault(): Promise<IndexSeries> {
  return apiGet<IndexSeries>("/analytics/index");
}

/** Which control is pressed for a response, checked against the wire
 * vocabulary.
 *
 * `requested_window`, NOT `default_window`. The two are equal on the first
 * load by construction, but they answer different questions the moment a
 * reader picks a window: `requested_window` is "which window is this payload
 * about" - the pressed button - while `default_window` remains the surface's
 * policy and is published throughout. Pressing the default would light the
 * wrong button on every subsequent selection.
 *
 * A defensive read, not a policy of its own: the token is used exactly as
 * published, and this only refuses a value outside the grammar the server
 * itself sent, which would otherwise leave the control with no pressed button
 * at all. The fallback is the FIRST window the server published, never a
 * hardcoded token, so a grammar change is followed rather than second-guessed.
 */
export function pressedWindow(series: IndexSeries): string {
  const offered = series.windows.map((row) => row.token);
  if (offered.includes(series.requested_window)) return series.requested_window;
  return offered[0] ?? series.requested_window;
}

// --- presentation -----------------------------------------------------------

/** A decimal string as an index level: "1000.1065" -> "1,000.11".
 *
 * Two places, because that is what the level is quoted in - it opens at
 * exactly 1000 and a day's move lives in the second decimal. Rounding for
 * display only; the string above is untouched. */
export function formatLevel(value: string | null): string | null {
  if (value === null) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** The server's `change.absolute`, signed. Never recomputed from points. */
export function formatAbsoluteChange(change: IndexChange): string {
  const n = Number(change.absolute);
  if (!Number.isFinite(n)) return "—";
  const body = Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${body}`;
}

/** The server's `change.pct`, signed, already IN percent units.
 *
 * `pct: "0.010650"` beside `absolute: "0.1065"` on a 1000-point base is
 * 0.01065 PER CENT, not 1.065%. Multiplying by 100 here would inflate every
 * figure on the page by two orders of magnitude, which on a flat index reads
 * as a plausible small move rather than as an obvious bug - so the unit is
 * asserted in a test rather than left to a reader to notice. */
export function formatPctChange(change: IndexChange): string {
  const n = Number(change.pct);
  if (!Number.isFinite(n)) return "—";
  const body = Math.abs(n).toFixed(2);
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${body}%`;
}

/** "Sep 3 – Sep 7, 2026", from the server's own covered bounds. */
export function formatCoveredRange(from: string | null, to: string | null): string | null {
  if (!from || !to) return null;
  const start = new Date(`${from}T00:00:00Z`);
  const end = new Date(`${to}T00:00:00Z`);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return null;
  const short = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
  const full = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
  return from === to ? full.format(end) : `${short.format(start)} – ${full.format(end)}`;
}

export function formatIndexDay(day: string): string {
  const parsed = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeZone: "UTC" }).format(parsed);
}

/** One contiguous run of days, and whether a real gap precedes it.
 *
 * `step_days > 1` means the archive genuinely holds nothing between two
 * points. Section 13.4 says such a join is drawn DASHED, because the alternative
 * - one solid stroke - claims a daily observation that was never made, and
 * inserting points to fill it would be inventing prices outright. Neither
 * happens: the run before and the run after are separate strokes, and the
 * dashed connector spans the two REAL endpoints and nothing else.
 *
 * A run is never split anywhere else. `step_days === null` occurs only on a
 * base point, which opens a run rather than breaking one.
 */
export interface IndexRun {
  /** Index into `points` of this run's first point. */
  start: number;
  points: IndexPoint[];
  /** The point this run joins back to across a gap, if any. */
  gapFrom: IndexPoint | null;
}

export function splitRuns(points: IndexPoint[]): IndexRun[] {
  const runs: IndexRun[] = [];
  points.forEach((point, i) => {
    const gap = point.step_days !== null && point.step_days > 1;
    if (i === 0 || gap) {
      runs.push({ start: i, points: [point], gapFrom: gap ? points[i - 1] : null });
      return;
    }
    runs[runs.length - 1].points.push(point);
  });
  return runs;
}

/** The y-domain, per methodology section 13.3.
 *
 * "A flat chart must not be cosmetically amplified." A fitted axis over
 * 1000.0000-1000.9577 spans one point in a thousand and turns a +0.096 % week
 * into a mountain range; the section's answer is a domain that includes the
 * segment base level and spans AT LEAST +/-1 % around it. That is what this
 * returns, widened only if real data falls outside.
 *
 * The anchor is the base point's own level when the window contains one, and
 * the window's `starting_value` otherwise - never a mean, and never the
 * midpoint of the data, both of which drift with the data they are supposed to
 * hold still against.
 *
 * Presentational arithmetic: it moves the AXIS, never a point.
 */
export function indexDomain(series: IndexSeries): [number, number] | null {
  const values = series.points.map((p) => Number(p.value)).filter((n) => Number.isFinite(n));
  if (values.length === 0) return null;

  const basePoint = series.points.find((p) => p.is_base);
  const anchorRaw = basePoint ? basePoint.value : series.starting_value;
  const anchor = Number(anchorRaw);
  const centre = Number.isFinite(anchor) ? anchor : values[0];

  const lo = Math.min(centre * 0.99, ...values);
  const hi = Math.max(centre * 1.01, ...values);
  return [lo, hi];
}
