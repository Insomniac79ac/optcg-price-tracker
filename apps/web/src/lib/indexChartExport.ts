/** Export the Card Pirate Index chart that is CURRENTLY ON SCREEN as a PNG.
 *
 * WHY THIS IS SPLIT IN TWO. `buildIndexExport` turns a response into a plain,
 * serialisable PLAN - every string already formatted, every segment already
 * decided - and `renderIndexExport` does nothing but paint that plan onto a
 * canvas. The split is what makes the honesty rules testable: a test can
 * assert that the plan carries the server's own headline strings, that a
 * snapshot gap is still a separate dashed segment, and that no point was
 * invented, without needing a real 2D context (jsdom has none).
 *
 * WHAT IS DELIBERATELY NOT DONE HERE
 * ----------------------------------
 * No refetch, no recompute, no slicing, no substitution. The plan is built
 * from the response the hero is already holding, so pressing Download cannot
 * produce a picture of data the reader was not looking at, and cannot issue a
 * second `/analytics/index` request. `splitRuns` and `indexDomain` are the
 * SAME functions the on-screen chart uses - imported, not reimplemented - so
 * a solid run, a dashed gap join and the y-domain cannot drift between the
 * screen and the file. The change figures are the server's `change.absolute`
 * and `change.pct` passed through the same formatters the headline uses;
 * nothing here divides, multiplies or accumulates a price.
 *
 * NO NEW DEPENDENCY. The whole path is `document.createElement("canvas")`,
 * `Path2D`, `canvas.toBlob` and an object URL - all browser primitives. A
 * DOM-to-image library would have been a large dependency to redraw a chart
 * whose geometry we already have in hand, and it would have rasterised the
 * page's background and layout into the file, which requirement 4 forbids.
 */

import {
  type IndexBreak,
  type IndexSeries,
  formatAbsoluteChange,
  formatCoveredRange,
  formatIndexDay,
  formatLevel,
  formatPctChange,
  indexDomain,
  isSnapshotGap,
  splitRuns,
  windowLabel,
} from "./cardPirateIndex";

/** The exported canvas, in CSS pixels before `scale`. 16:9 so the file drops
 * into a post or a slide without either axis being cropped. */
export const EXPORT_WIDTH = 1200;
export const EXPORT_HEIGHT = 675;
/** Rasterised at 2x, so the type is still crisp when the image is opened at
 * full size rather than as a thumbnail. */
export const EXPORT_SCALE = 2;

/** Brand tokens, resolved to literals ON PURPOSE.
 *
 * The file must not depend on the page it came from (requirement 4), and a
 * canvas cannot read a CSS custom property anyway - `ctx.fillStyle =
 * "var(--accent-gold)"` is silently ignored and leaves the previous colour.
 * These are the same values `docs/interface_design_system.md` defines, so the
 * export is the app's palette rather than a second one. */
export const EXPORT_COLORS = {
  background: "#171717", // --bg-page
  panel: "#1F1F21",
  grid: "#2E2E31", // --border-muted
  textPrimary: "#F4F0E8",
  textSecondary: "#BDB6A8",
  textMuted: "#8C877D",
  parchment: "#E8DEC7",
  gold: "#C79A4B", // --accent-gold
} as const;

/** Font stacks with real fallbacks. The hero passes the families actually
 * loaded on the page (next/font generates hashed names, so they cannot be
 * hardcoded); these are what a caller gets if it passes nothing. */
export interface ExportFonts {
  display: string;
  sans: string;
  mono: string;
}

export const DEFAULT_EXPORT_FONTS: ExportFonts = {
  display: 'Fraunces, Georgia, "Times New Roman", serif',
  sans: 'Manrope, "Helvetica Neue", Arial, sans-serif',
  mono: '"IBM Plex Mono", "SFMono-Regular", Consolas, monospace',
};

/** One stroke of the plotted series.
 *
 * `run` is a contiguous stretch of published days and is drawn solid. `gap`
 * spans the two REAL endpoints either side of a `step_days > 1` hole and is
 * drawn dashed - section 13.4's rule, carried into the export unchanged. A
 * gap segment therefore always has exactly two points, and there is never a
 * third point invented between them. */
export interface IndexExportSegment {
  kind: "run" | "gap";
  points: { date: string; t: number; value: number }[];
}

export interface IndexExportPlan {
  filename: string;
  title: string;
  /** The window the response is about - `series.requested_window`, echoed. */
  windowToken: string;
  windowLabel: string;
  coveredRange: string | null;
  /** Headline figures, already formatted from the server's own fields. */
  level: string | null;
  start: string | null;
  high: string | null;
  low: string | null;
  absoluteChange: string | null;
  pctChange: string | null;
  /** The server's reason, in the same words the page shows, when `change` is
   * null. Never a zero standing in for an absence. */
  changeUnavailable: string | null;
  spansBreak: boolean;
  partialHistory: boolean;
  segments: IndexExportSegment[];
  /** Methodology boundaries, from `series.breaks` only. */
  breaks: { at: string; t: number; label: string }[];
  /** Exactly the axis the screen used. */
  yDomain: [number, number];
  xDomain: [number, number];
  watermark: boolean;
  attribution: string;
  disclaimer: string;
  width: number;
  height: number;
  scale: number;
  background: string;
}

const CHANGE_UNAVAILABLE_COPY = "Change not available across this period";

function dayStamp(now: Date): string {
  return now.toISOString().slice(0, 10);
}

/** `card-pirate-index-all-2026-09-08.png`.
 *
 * The window token names WHICH chart this is, and the date is when the file
 * was generated - the two things a reader needs to tell two downloads apart
 * in a folder. The token is squeezed through the same character class as the
 * rest of the grammar so an unexpected value can never travel into a path. */
export function indexExportFilename(windowToken: string, now: Date): string {
  const token = windowToken.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return `card-pirate-index-${token || "window"}-${dayStamp(now)}.png`;
}

function breakLabel(entry: IndexBreak): string {
  return `Methodology change — ${formatIndexDay(entry.at)}`;
}

/** The plan, or `null` when there is genuinely nothing to draw.
 *
 * `null` is the honest answer for an empty window, and it is what disables
 * the button. The alternative - exporting an empty frame with a headline on
 * it - would be a picture of a chart that does not exist.
 */
export function buildIndexExport(
  series: IndexSeries,
  options: { now?: Date } = {},
): IndexExportPlan | null {
  if (series.points.length === 0) return null;

  const domain = indexDomain(series);
  if (domain === null) return null;

  const now = options.now ?? new Date();
  const token = series.requested_window;

  // The same split the chart draws, from the same function. A run becomes a
  // solid stroke; the join across a real hole becomes its own dashed stroke
  // between the two endpoints that actually exist.
  const runs = splitRuns(series.points);
  const segments: IndexExportSegment[] = [];
  for (const run of runs) {
    if (run.gapFrom) {
      segments.push({
        kind: "gap",
        points: [toPoint(run.gapFrom.date, run.gapFrom.value), toPoint(run.points[0].date, run.points[0].value)],
      });
    }
    segments.push({
      kind: "run",
      points: run.points.map((p) => toPoint(p.date, p.value)),
    });
  }

  const ts = series.points.map((p) => Date.parse(`${p.date}T00:00:00Z`));
  const xDomain: [number, number] = [Math.min(...ts), Math.max(...ts)];

  return {
    filename: indexExportFilename(token, now),
    title: "Card Pirate Index",
    windowToken: token,
    windowLabel: windowLabel(token),
    coveredRange: formatCoveredRange(series.available_from, series.available_to),
    level: formatLevel(series.current_value),
    start: formatLevel(series.starting_value),
    high: formatLevel(series.high_value),
    low: formatLevel(series.low_value),
    absoluteChange: series.change ? formatAbsoluteChange(series.change) : null,
    pctChange: series.change ? formatPctChange(series.change) : null,
    changeUnavailable: series.change ? null : CHANGE_UNAVAILABLE_COPY,
    spansBreak: series.change?.spans_break ?? false,
    partialHistory: !series.covers_requested_window,
    segments,
    // Version boundaries only - a snapshot gap is already carried by the
    // dashed segment above, and marking it again would say "the methodology
    // changed here" about a cadence fact.
    breaks: series.breaks
      .filter((entry) => !isSnapshotGap(entry))
      .map((entry) => ({
        at: entry.at,
        t: Date.parse(`${entry.at}T00:00:00Z`),
        label: breakLabel(entry),
      })),
    yDomain: domain,
    xDomain,
    watermark: true,
    attribution: "CardPirate",
    disclaimer: "Not a price. Not investment advice.",
    width: EXPORT_WIDTH,
    height: EXPORT_HEIGHT,
    scale: EXPORT_SCALE,
    background: EXPORT_COLORS.background,
  };
}

function toPoint(date: string, value: string): { date: string; t: number; value: number } {
  return { date, t: Date.parse(`${date}T00:00:00Z`), value: Number(value) };
}

// --- rendering ---------------------------------------------------------------

/** The Atlas mark's own path data, lifted verbatim from
 * `components/brand/AtlasMark.tsx`.
 *
 * There is one Atlas mark and this is it - the strings below are the same
 * `d` attributes that component renders, replayed through `Path2D` because a
 * canvas cannot mount a React SVG. Copying the GEOMETRY rather than inventing
 * a second mark is the point; if the mark changes, these change with it.
 * viewBox is 32x40. */
const ATLAS_PATHS = {
  card: "M6 2 L24 2 L28 6 L28 34 A2 2 0 0 1 26 36 L6 36 A2 2 0 0 1 4 34 L4 4 A2 2 0 0 1 6 2 Z",
  fold: "M21.5 4 L25.5 7.5",
  route: "M8 30 Q9 22 14 19",
  north: "M16 10 L18.5 19 L13.5 19 Z",
  south: "M16 28 L18.5 19 L13.5 19 Z",
} as const;

function drawAtlasMark(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  size: number,
  opacity: number,
): void {
  ctx.save();
  ctx.globalAlpha = opacity;
  ctx.translate(x, y);
  ctx.scale(size / 32, size / 32);
  ctx.lineWidth = 1.6;
  ctx.strokeStyle = EXPORT_COLORS.parchment;
  ctx.stroke(new Path2D(ATLAS_PATHS.card));
  ctx.lineWidth = 1;
  ctx.stroke(new Path2D(ATLAS_PATHS.fold));
  ctx.setLineDash([1.4, 2.6]);
  ctx.stroke(new Path2D(ATLAS_PATHS.route));
  ctx.setLineDash([]);
  ctx.fillStyle = EXPORT_COLORS.gold;
  ctx.fill(new Path2D(ATLAS_PATHS.north));
  ctx.fillStyle = "#4F8D86";
  ctx.fill(new Path2D(ATLAS_PATHS.south));
  ctx.restore();
}

/** Plot insets. `top` clears the stat row AND the break glyph that is drawn
 * just above the plot boundary - at the first value the topmost y-axis label
 * and the diamond both landed inside the START/HIGH/LOW row. */
const PLOT = { left: 96, right: 48, top: 280, bottom: 92 };

/** Paint a plan onto a fresh canvas. Browser-only: needs a real 2D context. */
export function renderIndexExport(
  plan: IndexExportPlan,
  options: { fonts?: ExportFonts; document?: Document } = {},
): HTMLCanvasElement {
  const doc = options.document ?? document;
  const fonts = options.fonts ?? DEFAULT_EXPORT_FONTS;
  const canvas = doc.createElement("canvas");
  canvas.width = plan.width * plan.scale;
  canvas.height = plan.height * plan.scale;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas 2d context unavailable");
  ctx.scale(plan.scale, plan.scale);

  // SELF-CONTAINED: an opaque ground of its own, so the file never borrows
  // the page's background and never arrives with a transparent bed that a
  // dark viewer turns into unreadable text.
  ctx.fillStyle = plan.background;
  ctx.fillRect(0, 0, plan.width, plan.height);

  const plotX = PLOT.left;
  const plotY = PLOT.top;
  const plotW = plan.width - PLOT.left - PLOT.right;
  const plotH = plan.height - PLOT.top - PLOT.bottom;

  // --- header -------------------------------------------------------------
  drawAtlasMark(ctx, 48, 44, 40, 0.95);
  ctx.fillStyle = EXPORT_COLORS.textPrimary;
  ctx.font = `600 30px ${fonts.display}`;
  ctx.textBaseline = "alphabetic";
  ctx.fillText(plan.title, 104, 76);

  ctx.font = `500 13px ${fonts.mono}`;
  ctx.fillStyle = EXPORT_COLORS.textMuted;
  const meta = [plan.windowLabel.toUpperCase(), plan.coveredRange].filter(Boolean).join("   ");
  ctx.fillText(meta, 104, 98);

  // --- headline -----------------------------------------------------------
  ctx.fillStyle = EXPORT_COLORS.textPrimary;
  ctx.font = `600 62px ${fonts.display}`;
  ctx.fillText(plan.level ?? "—", 48, 172);
  const levelWidth = ctx.measureText(plan.level ?? "—").width;

  if (plan.changeUnavailable) {
    ctx.font = `500 16px ${fonts.sans}`;
    ctx.fillStyle = EXPORT_COLORS.textMuted;
    ctx.fillText(plan.changeUnavailable, 48 + levelWidth + 20, 168);
  } else {
    ctx.font = `600 24px ${fonts.display}`;
    ctx.fillStyle = EXPORT_COLORS.gold;
    ctx.fillText(plan.absoluteChange ?? "—", 48 + levelWidth + 20, 168);
    const absWidth = ctx.measureText(plan.absoluteChange ?? "—").width;
    ctx.font = `500 18px ${fonts.sans}`;
    const pctX = 48 + levelWidth + 32 + absWidth;
    ctx.fillText(plan.pctChange ?? "—", pctX, 168);
    if (plan.spansBreak) {
      // INLINE, not stacked. Below the percentage it sat in the same column as
      // the LOW stat's label and read as that stat's caption.
      const pctWidth = ctx.measureText(plan.pctChange ?? "—").width;
      ctx.font = `500 11px ${fonts.mono}`;
      ctx.fillStyle = EXPORT_COLORS.textMuted;
      ctx.fillText("LINKED", pctX + pctWidth + 14, 166);
    }
  }

  // Start / High / Low, in the same order and words as the hero's stat row.
  const stats: [string, string | null][] = [
    ["START", plan.start],
    ["HIGH", plan.high],
    ["LOW", plan.low],
  ];
  stats.forEach(([label, value], i) => {
    const x = 48 + i * 150;
    ctx.font = `500 10px ${fonts.mono}`;
    ctx.fillStyle = EXPORT_COLORS.textMuted;
    ctx.fillText(label, x, 208);
    ctx.font = `500 17px ${fonts.sans}`;
    ctx.fillStyle = EXPORT_COLORS.textSecondary;
    ctx.fillText(value ?? "—", x, 228);
  });

  // --- plot ---------------------------------------------------------------
  const [lo, hi] = plan.yDomain;
  const [t0, t1] = plan.xDomain;
  const span = hi - lo || 1;
  const tSpan = t1 - t0 || 1;
  const px = (t: number) => plotX + ((t - t0) / tSpan) * plotW;
  const py = (v: number) => plotY + plotH - ((v - lo) / span) * plotH;

  ctx.strokeStyle = EXPORT_COLORS.grid;
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = plotY + (plotH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(plotX, y);
    ctx.lineTo(plotX + plotW, y);
    ctx.stroke();
    const value = hi - (span / 4) * i;
    ctx.font = `500 11px ${fonts.mono}`;
    ctx.fillStyle = EXPORT_COLORS.textMuted;
    ctx.textAlign = "right";
    ctx.fillText(value.toLocaleString("en-US", { maximumFractionDigits: 0 }), plotX - 12, y + 4);
    ctx.textAlign = "left";
  }

  // The watermark sits inside the plot, behind the data, exactly as on screen.
  if (plan.watermark) {
    drawAtlasMark(ctx, plotX + 24, plotY + plotH - 132, 108, 0.07);
  }

  // Boundaries first, so the line is drawn over them and stays continuous
  // through a version change - section 13.4 row 1.
  for (const entry of plan.breaks) {
    const x = px(entry.t);
    ctx.save();
    ctx.strokeStyle = EXPORT_COLORS.parchment;
    ctx.globalAlpha = 0.6;
    ctx.setLineDash([2, 3]);
    ctx.beginPath();
    ctx.moveTo(x, plotY);
    ctx.lineTo(x, plotY + plotH);
    ctx.stroke();
    ctx.restore();
    ctx.fillStyle = EXPORT_COLORS.textSecondary;
    ctx.font = `12px ${fonts.sans}`;
    ctx.textAlign = "center";
    ctx.fillText("◆", x, plotY - 6);
    ctx.textAlign = "left";
  }

  for (const segment of plan.segments) {
    if (segment.points.length === 0) continue;
    ctx.save();
    ctx.strokeStyle = EXPORT_COLORS.gold;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    if (segment.kind === "gap") {
      ctx.setLineDash([3, 4]);
      ctx.globalAlpha = 0.7;
      ctx.lineWidth = 1.25;
    } else {
      ctx.lineWidth = 2;
    }
    ctx.beginPath();
    segment.points.forEach((p, i) => {
      const x = px(p.t);
      const y = py(p.value);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    // A single-point run has no line to draw; mark it so a one-day window is
    // still visibly a measurement rather than an empty plot.
    if (segment.kind === "run" && segment.points.length === 1) {
      ctx.fillStyle = EXPORT_COLORS.gold;
      ctx.arc(px(segment.points[0].t), py(segment.points[0].value), 3, 0, Math.PI * 2);
      ctx.fill();
    } else {
      ctx.stroke();
    }
    ctx.restore();
  }

  // x labels: the first and last published day, from the points themselves.
  const first = plan.segments[0]?.points[0];
  const lastSegment = plan.segments[plan.segments.length - 1];
  const last = lastSegment?.points[lastSegment.points.length - 1];
  ctx.font = `500 11px ${fonts.mono}`;
  ctx.fillStyle = EXPORT_COLORS.textMuted;
  if (first) ctx.fillText(formatIndexDay(first.date), plotX, plotY + plotH + 24);
  if (last && last.date !== first?.date) {
    ctx.textAlign = "right";
    ctx.fillText(formatIndexDay(last.date), plotX + plotW, plotY + plotH + 24);
    ctx.textAlign = "left";
  }

  // --- footer -------------------------------------------------------------
  ctx.font = `500 12px ${fonts.sans}`;
  ctx.fillStyle = EXPORT_COLORS.textMuted;
  const notes = [plan.partialHistory ? "Showing available history only." : null, plan.disclaimer]
    .filter(Boolean)
    .join(" ");
  ctx.fillText(notes, 48, plan.height - 34);

  ctx.font = `600 13px ${fonts.mono}`;
  ctx.fillStyle = EXPORT_COLORS.parchment;
  ctx.textAlign = "right";
  ctx.fillText(plan.attribution, plan.width - 48, plan.height - 34);
  ctx.textAlign = "left";

  return canvas;
}

/** Rasterise and hand the file to the browser.
 *
 * Never throws at the call site: a canvas the UA refuses to encode, a blob
 * that comes back null, or a browser without `toBlob` all resolve to `false`
 * so the hero can say so quietly instead of the page dying inside a click
 * handler.
 */
export async function downloadIndexExport(
  plan: IndexExportPlan,
  options: { fonts?: ExportFonts; document?: Document } = {},
): Promise<boolean> {
  const doc = options.document ?? document;
  try {
    const canvas = renderIndexExport(plan, { ...options, document: doc });
    if (typeof canvas.toBlob !== "function") return false;
    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob((result) => resolve(result), "image/png");
    });
    if (!blob) return false;
    const url = URL.createObjectURL(blob);
    const anchor = doc.createElement("a");
    anchor.href = url;
    anchor.download = plan.filename;
    doc.body.appendChild(anchor);
    anchor.click();
    doc.body.removeChild(anchor);
    // Revoked on the next turn so the navigation the click started has
    // already taken its reference to the blob.
    setTimeout(() => URL.revokeObjectURL(url), 0);
    return true;
  } catch {
    return false;
  }
}

/** The font families ACTUALLY loaded on the page.
 *
 * `next/font` generates hashed family names (`__Fraunces_1a2b3c`), so the
 * export cannot name them; it reads them off a live element instead and falls
 * back to the generic stacks when there is no DOM to read (SSR, tests).
 */
export function resolveExportFonts(element: Element | null): ExportFonts {
  if (!element || typeof getComputedStyle !== "function") return DEFAULT_EXPORT_FONTS;
  const style = getComputedStyle(element);
  const display = style.getPropertyValue("--font-display").trim();
  const sans = style.getPropertyValue("--font-sans").trim();
  const mono = style.getPropertyValue("--font-mono").trim();
  return {
    display: display || DEFAULT_EXPORT_FONTS.display,
    sans: sans || DEFAULT_EXPORT_FONTS.sans,
    mono: mono || DEFAULT_EXPORT_FONTS.mono,
  };
}
