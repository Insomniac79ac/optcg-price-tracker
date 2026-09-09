/** Export ONE EXACT PRINT's analytics chart as a PNG.
 *
 * WHY THIS IS SPLIT IN TWO. `buildPrintChartExport` turns the analytics
 * response into a plain, serialisable PLAN - every string already formatted,
 * every stroke already decided - and `renderPrintChartExport` does nothing but
 * paint that plan onto a canvas. The split is what makes the honesty rules
 * testable: a test can assert that the plan carries the server's own headline
 * figures, that a methodology break is still two separate strokes, and that no
 * point was invented, without needing a real 2D context (jsdom has none).
 *
 * WHAT IS DELIBERATELY NOT DONE HERE
 * ----------------------------------
 * No refetch, no recompute, no re-slicing, no substitution. The plan is built
 * from the `PrintAnalytics` object the page is ALREADY HOLDING, so pressing
 * Download cannot issue a second request and cannot produce a picture of a
 * window the reader was not looking at. `buildSeriesChartModel` is the SAME
 * function the on-screen chart uses - imported, not reimplemented - so the
 * strokes, the breaks and which points are plottable cannot drift between the
 * screen and the file.
 *
 * THE THREE SERIES ARE NOT THE SAME KIND OF NUMBER, AND THE FILE SAYS SO.
 * Market Index is Atlas's own archived aggregate; Yuyu-Tei is a shop's asking
 * price; SNKRDUNK is a marketplace's cheapest open listing. The legend names
 * each platform and carries its instrument, exactly as the on-screen chips do.
 * There is no generic "Market Price" label anywhere here, because collapsing
 * three different claims into one word is the specific untruth this chart
 * exists to avoid.
 *
 * A SERIES THAT IS NOT THERE IS SIMPLY ABSENT. A print with no Yuyu-Tei
 * history gets no Yuyu-Tei line and no Yuyu-Tei legend entry - never a flat
 * line at zero, never a dashed "no data" rail, never the other platform's
 * numbers standing in for it.
 */

import {
  buildSeriesChartModel,
  dayToTime,
  formatSeriesDay,
  seriesInstrumentLabel,
  seriesPaintOrder,
  seriesPlatformLabel,
  type PrintSeries,
  type SeriesStroke,
} from "./printSeries";
import {
  changeUnavailableCopy,
  windowLabel,
  type PrintAnalytics,
} from "./printAnalytics";
import { formatJpy } from "./format";
import {
  DEFAULT_EXPORT_FONTS,
  EXPORT_COLORS,
  EXPORT_HEIGHT,
  EXPORT_SCALE,
  EXPORT_WIDTH,
  createExportCanvas,
  dayStamp,
  downloadCanvasPng,
  drawAtlasMark,
  type ExportFonts,
} from "./chartExport";
import { safeFilenameToken } from "./chartExport";

/** One drawable stroke, flattened to canvas coordinates' inputs.
 *
 * A stroke NEVER spans a server segment, so two strokes either side of a
 * methodology break have no path between them to draw - the same mechanism
 * the on-screen chart uses, carried into the file unchanged. There is
 * deliberately no "gap" stroke kind here: unlike the aggregate Index, which
 * joins across a snapshot hole with a dashed line, this chart draws nothing
 * across a break at all.
 */
export interface PrintExportStroke {
  seriesKey: string;
  color: string;
  points: { t: number; value: number }[];
}

export interface PrintExportSeries {
  key: string;
  /** Carried so the renderer can apply the paint order without re-deriving it
   * from the key string. */
  kind: "market_index" | "source";
  /** "Market Index", "Yuyu-Tei", "SNKRDUNK" - the platform, never generic. */
  label: string;
  /** "Retail price", "Current listing" - what this platform's number IS.
   * Null for the Market Index, which is not quoted by anyone. */
  instrument: string | null;
  color: string;
  strokes: PrintExportStroke[];
}

export interface PrintExportPlan {
  filename: string;
  /** The card, as the page names it. */
  title: string;
  /** `OP01-001 · Alt Art · OP-01` - the exact-print identity line. */
  subtitle: string;
  /** `#1` - the print id, because a card code is a family name and 955 codes
   * in the catalogue carry more than one print. */
  printRef: string;
  windowToken: string;
  windowLabel: string;
  /** `Aug 9, 2026 — Sep 9, 2026`, from the plotted domain. */
  coveredRange: string | null;
  /** Archived Market Index headline, already formatted from the server's own
   * fields. Never recomputed from the points below. */
  current: string | null;
  currentAsOf: string | null;
  start: string | null;
  high: string | null;
  low: string | null;
  absoluteChange: string | null;
  pctChange: string | null;
  /** The server's reason, in the same words the page shows, when `change` is
   * null. Never a zero standing in for an absence. */
  changeUnavailable: string | null;
  spansBreak: boolean;
  observedDays: number;
  series: PrintExportSeries[];
  /** Methodology boundaries, from the model's own break markers. */
  breaks: { t: number; color: string }[];
  breakNote: string | null;
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

/** Series colours, matched to the on-screen chart so a reader who saw the
 * chart recognises the file. Kept as literals for the same reason the palette
 * is: a canvas cannot read a CSS custom property, so the screen's
 * `var(--accent-gold)` would be silently ignored here. */
const SERIES_COLOR: Record<string, string> = {
  market_index: EXPORT_COLORS.gold,
  "source:yuyutei": EXPORT_COLORS.teal,
  "source:snkrdunk": EXPORT_COLORS.parchment,
};

/** The screen's fallback ramp, as canvas literals - for a platform Atlas
 * starts collecting tomorrow, which the chart already draws without a code
 * change and which the file must therefore also be able to draw. */
const FALLBACK_COLORS = ["#A78BFA", "#C8624D", "#8B8672"];

function colorFor(key: string, index: number): string {
  return SERIES_COLOR[key] ?? FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}

/** `card-pirate-op01-001-1-all-2026-09-09.png`.
 *
 * Card code AND print id, because the code alone does not identify a print -
 * a family name would give two different cards the same filename. Every
 * segment goes through the same character class, so an unexpected code, a
 * window token this build has never heard of, or a name carrying `..` all come
 * out inert.
 */
export function printExportFilename(
  cardCode: string,
  printId: number | string,
  windowToken: string,
  now: Date,
): string {
  return [
    "card-pirate",
    safeFilenameToken(cardCode, "print"),
    safeFilenameToken(String(printId), "id"),
    safeFilenameToken(windowToken, "window"),
    dayStamp(now),
  ].join("-") + ".png";
}

/** The card's identity, as the export should name it. Supplied by the caller
 * from the print payload, because `/analytics` deliberately carries no
 * identity fields - print identity stays on `GET /prints/{id}`. */
export interface PrintExportIdentity {
  cardCode: string;
  displayName: string;
  printingLabel: string | null;
  releaseCode: string | null;
}

/** Turn the response the page is holding into a plan, or null when there is
 * genuinely nothing to draw.
 *
 * Null - not an empty chart - when no selected series has a single plottable
 * point in this window. A picture of an empty axis asserts that Atlas looked
 * and found nothing, which is a different claim from "there is nothing here to
 * publish"; the caller declines to offer the download instead.
 */
export function buildPrintChartExport(
  analytics: PrintAnalytics | null,
  identity: PrintExportIdentity,
  options: { now?: Date; selectedKeys?: ReadonlySet<string> } = {},
): PrintExportPlan | null {
  if (!analytics) return null;
  const now = options.now ?? new Date();

  // The SAME model the screen draws, so nothing can differ between them.
  const selected =
    options.selectedKeys ?? new Set(analytics.series.map((entry: PrintSeries) => entry.key));
  const model = buildSeriesChartModel(analytics, selected);
  if (!model.hasPoints || model.rows.length === 0) return null;

  // SERVER ORDER, not paint order. `seriesPaintOrder` exists to decide which
  // line is drawn on top of which - and its own contract is that the legend,
  // the tooltip and the colour assignment all keep the server's order. Building
  // the plan in paint order put the legend in a different order from the chips
  // above the chart, and would have handed an unknown platform a different
  // fallback colour in the file than it has on screen. The renderer applies the
  // paint order itself, at the moment it strokes.
  const series: PrintExportSeries[] = model.series
    .map((entry, index) => {
      const color = colorFor(entry.key, index);
      const strokes: PrintExportStroke[] = entry.strokes
        .map((stroke: SeriesStroke) => ({
          seriesKey: entry.key,
          color,
          points: stroke.points
            .filter((p) => p.value_jpy !== null && p.eligible !== false)
            .map((p) => ({ t: dayToTime(p.day), value: p.value_jpy as number })),
        }))
        .filter((stroke) => stroke.points.length > 0);
      // THE SAME TWO HELPERS THE ON-SCREEN CHIPS USE, split so the legend can
      // weight the platform and its instrument differently. Reused rather than
      // reimplemented: a second copy of "what is this platform's number
      // called" is exactly how a file starts saying something the chart above
      // it does not.
      const source = analytics.series.find((s) => s.key === entry.key);
      return {
        key: entry.key,
        kind: entry.kind,
        label: source ? seriesPlatformLabel(source) : entry.label,
        // Null in three honest ways: the Market Index is not quoted in an
        // instrument at all, an unconfigured source has none named, and a
        // series whose instrument CHANGED has more than one - and labelling
        // old points with the latest measurement would be a claim about days
        // that were not taken under it.
        instrument: source ? seriesInstrumentLabel(source) : null,
        color,
        strokes,
      };
    })
    // A platform with nothing on the line is ABSENT from the file, not drawn
    // flat. It has no legend entry either: a legend entry for a line that is
    // not there is a claim the picture does not support.
    .filter((entry) => entry.strokes.length > 0);

  if (series.length === 0) return null;

  const values = series.flatMap((s) => s.strokes.flatMap((k) => k.points.map((p) => p.value)));
  const times = series.flatMap((s) => s.strokes.flatMap((k) => k.points.map((p) => p.t)));
  if (values.length === 0 || times.length === 0) return null;

  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const t0 = Math.min(...times);
  const t1 = Math.max(...times);

  const head = analytics.headline;
  const plottedKeys = new Set(series.map((entry) => entry.key));
  const breaks = model.breaks
    // Only boundaries belonging to a series the file actually draws.
    .filter((marker) => plottedKeys.has(marker.seriesKey))
    .map((marker) => ({
      t: marker.t,
      color: series.find((entry) => entry.key === marker.seriesKey)?.color ?? EXPORT_COLORS.grid,
    }));

  const subtitle = [
    identity.cardCode,
    identity.printingLabel,
    identity.releaseCode ? `Found in ${identity.releaseCode}` : null,
  ]
    .filter(Boolean)
    .join("  ·  ");

  return {
    filename: printExportFilename(
      identity.cardCode,
      analytics.card_print_id,
      analytics.requested_window,
      now,
    ),
    title: identity.displayName,
    subtitle,
    printRef: `#${analytics.card_print_id}`,
    windowToken: analytics.requested_window,
    windowLabel: windowLabel(analytics.requested_window),
    coveredRange: `${formatSeriesDay(isoDay(t0))} — ${formatSeriesDay(isoDay(t1))}`,
    // EVERY ONE OF THESE IS THE SERVER'S. Formatted, never derived: the high
    // below is `headline.high_value_jpy`, not the maximum of the points above,
    // and the two can legitimately differ because the headline spans the
    // archived Market Index alone while the plot spans every series.
    current: head.current_value_jpy === null ? null : formatJpy(head.current_value_jpy),
    currentAsOf: head.current_as_of ? formatSeriesDay(head.current_as_of) : null,
    start: head.starting_value_jpy === null ? null : formatJpy(head.starting_value_jpy),
    high: head.high_value_jpy === null ? null : formatJpy(head.high_value_jpy),
    low: head.low_value_jpy === null ? null : formatJpy(head.low_value_jpy),
    absoluteChange: head.change ? signedJpy(head.change.absolute_jpy) : null,
    pctChange: head.change ? signedPct(head.change.pct) : null,
    changeUnavailable: head.change
      ? null
      : (changeUnavailableCopy(head.change_unavailable_reason) ??
        "No comparable change to report for this window."),
    spansBreak: head.change?.spans_break ?? false,
    observedDays: head.observed_days,
    series,
    breaks,
    breakNote:
      breaks.length > 0
        ? "Dashed marks show where the measurement changed. Lines are not joined across them."
        : null,
    yDomain: [lo, hi],
    xDomain: [t0, t1],
    watermark: true,
    attribution: "CardPirate",
    disclaimer: "Recorded prices, not a valuation. Not investment advice.",
    width: EXPORT_WIDTH,
    height: EXPORT_HEIGHT,
    scale: EXPORT_SCALE,
    background: EXPORT_COLORS.background,
  };
}

function isoDay(t: number): string {
  return new Date(t).toISOString().slice(0, 10);
}

/** The server's own absolute change, signed for display. Never computed. */
function signedJpy(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${formatJpy(Math.abs(value))}`;
}

function signedPct(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(2)}%`;
}

// --- rendering ---------------------------------------------------------------

/** Plot insets. Deeper `top` than the Index export's, because this file
 * carries a card identity line and an `As of` stamp the Index has no need of,
 * and a taller `bottom` for the legend, which names three platforms and their
 * instruments rather than one index. */
const PLOT = { left: 104, right: 48, top: 250, bottom: 118 };

/** Paint a plan onto a fresh canvas. Browser-only: needs a real 2D context. */
export function renderPrintChartExport(
  plan: PrintExportPlan,
  options: { fonts?: ExportFonts; document?: Document } = {},
): HTMLCanvasElement {
  const doc = options.document ?? document;
  const fonts = options.fonts ?? DEFAULT_EXPORT_FONTS;
  const { canvas, ctx } = createExportCanvas(plan, doc);

  const plotX = PLOT.left;
  const plotY = PLOT.top;
  const plotW = plan.width - PLOT.left - PLOT.right;
  const plotH = plan.height - PLOT.top - PLOT.bottom;

  // --- header -------------------------------------------------------------
  drawAtlasMark(ctx, 48, 44, 40, 0.95);
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = EXPORT_COLORS.textPrimary;
  ctx.font = `600 30px ${fonts.display}`;
  ctx.fillText(plan.title, 104, 74);

  ctx.font = `500 13px ${fonts.mono}`;
  ctx.fillStyle = EXPORT_COLORS.textMuted;
  ctx.fillText(`${plan.subtitle}  ·  ${plan.printRef}`, 104, 96);

  // The window, right-aligned against the title so the file says WHICH span
  // it is a picture of without the reader hunting for it.
  ctx.textAlign = "right";
  ctx.font = `500 13px ${fonts.mono}`;
  ctx.fillStyle = EXPORT_COLORS.textSecondary;
  ctx.fillText(plan.windowLabel.toUpperCase(), plan.width - 48, 74);
  if (plan.coveredRange) {
    ctx.fillStyle = EXPORT_COLORS.textMuted;
    ctx.fillText(plan.coveredRange, plan.width - 48, 96);
  }
  ctx.textAlign = "left";

  // --- archived headline --------------------------------------------------
  ctx.font = `500 10px ${fonts.mono}`;
  ctx.fillStyle = EXPORT_COLORS.textMuted;
  ctx.fillText("MARKET INDEX", 48, 140);

  ctx.fillStyle = EXPORT_COLORS.gold;
  ctx.font = `600 52px ${fonts.display}`;
  ctx.fillText(plan.current ?? "—", 48, 186);
  const currentWidth = ctx.measureText(plan.current ?? "—").width;

  let cursor = 48 + currentWidth + 18;
  if (plan.currentAsOf) {
    ctx.font = `500 13px ${fonts.sans}`;
    ctx.fillStyle = EXPORT_COLORS.textMuted;
    ctx.fillText(`As of ${plan.currentAsOf}`, cursor, 186);
    cursor += ctx.measureText(`As of ${plan.currentAsOf}`).width + 22;
  }

  if (plan.changeUnavailable) {
    // THE REFUSAL IS THE CONTENT. A window crossing a methodology boundary
    // has no comparable change, and printing the server's reason is what
    // keeps a visibly sloped chart from reading as an unreported movement.
    ctx.font = `500 14px ${fonts.sans}`;
    ctx.fillStyle = EXPORT_COLORS.textMuted;
    ctx.fillText(plan.changeUnavailable, cursor, 186);
  } else {
    ctx.font = `600 22px ${fonts.display}`;
    ctx.fillStyle = EXPORT_COLORS.textPrimary;
    ctx.fillText(plan.absoluteChange ?? "—", cursor, 186);
    const absWidth = ctx.measureText(plan.absoluteChange ?? "—").width;
    ctx.font = `500 16px ${fonts.sans}`;
    ctx.fillStyle = EXPORT_COLORS.textSecondary;
    ctx.fillText(plan.pctChange ?? "—", cursor + absWidth + 12, 186);
    if (plan.spansBreak) {
      const pctWidth = ctx.measureText(plan.pctChange ?? "—").width;
      ctx.font = `500 11px ${fonts.mono}`;
      ctx.fillStyle = EXPORT_COLORS.textMuted;
      ctx.fillText("LINKED", cursor + absWidth + pctWidth + 26, 184);
    }
  }

  // Starting / High / Low / Observed, in the same order and words as the page.
  const stats: [string, string][] = [
    ["STARTING", plan.start ?? "—"],
    ["HIGH", plan.high ?? "—"],
    ["LOW", plan.low ?? "—"],
    ["OBSERVED", `${plan.observedDays} ${plan.observedDays === 1 ? "day" : "days"}`],
  ];
  stats.forEach(([label, value], i) => {
    const x = 48 + i * 150;
    ctx.font = `500 10px ${fonts.mono}`;
    ctx.fillStyle = EXPORT_COLORS.textMuted;
    ctx.fillText(label, x, 216);
    ctx.font = `500 17px ${fonts.sans}`;
    ctx.fillStyle = EXPORT_COLORS.textSecondary;
    ctx.fillText(value, x, 236);
  });

  // --- plot ---------------------------------------------------------------
  const [lo, hi] = plan.yDomain;
  const [t0, t1] = plan.xDomain;
  // The same 5%/5% padding the on-screen y-axis uses.
  const padLo = lo * 0.95;
  const padHi = hi * 1.05;
  const span = padHi - padLo || 1;
  const tSpan = t1 - t0 || 1;
  const px = (t: number) => plotX + ((t - t0) / tSpan) * plotW;
  const py = (v: number) => plotY + plotH - ((v - padLo) / span) * plotH;

  // Gridlines and y labels.
  ctx.strokeStyle = EXPORT_COLORS.grid;
  ctx.lineWidth = 1;
  ctx.font = `500 12px ${fonts.mono}`;
  for (let i = 0; i <= 4; i++) {
    const y = plotY + (plotH * i) / 4;
    ctx.beginPath();
    ctx.moveTo(plotX, y);
    ctx.lineTo(plotX + plotW, y);
    ctx.stroke();
    ctx.fillStyle = EXPORT_COLORS.textMuted;
    ctx.textAlign = "right";
    ctx.fillText(formatJpy(Math.round(padHi - (span * i) / 4)), plotX - 12, y + 4);
    ctx.textAlign = "left";
  }

  // The watermark sits INSIDE the plot and BEHIND the data, exactly as on
  // screen - drawn before the strokes so no line is ever painted under it.
  if (plan.watermark) {
    drawAtlasMark(ctx, plotX + 20, plotY + plotH - 128, 104, 0.07);
  }

  // Methodology boundaries, in the owning series' colour.
  plan.breaks.forEach((mark) => {
    ctx.save();
    ctx.strokeStyle = mark.color;
    ctx.globalAlpha = 0.5;
    ctx.setLineDash([3, 5]);
    ctx.beginPath();
    ctx.moveTo(px(mark.t), plotY);
    ctx.lineTo(px(mark.t), plotY + plotH);
    ctx.stroke();
    ctx.restore();
  });

  // ONE PATH PER STROKE. Two strokes either side of a break are two paths,
  // so there is nothing for the renderer to join across the boundary however
  // the data moves - the on-screen mechanism, carried into the file.
  // PAINT ORDER APPLIED HERE, and only here. The Market Index goes last and
  // narrower, so a platform it agrees with shows as a halo either side rather
  // than being hidden underneath it - the same reasoning the on-screen chart
  // uses. The legend above kept the server's order.
  seriesPaintOrder(plan.series).forEach((entry) => {
    const isIndex = entry.key === "market_index";
    entry.strokes.forEach((stroke) => {
      ctx.save();
      ctx.strokeStyle = entry.color;
      ctx.lineWidth = isIndex ? 2 : 2.6;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.beginPath();
      stroke.points.forEach((point, i) => {
        const x = px(point.t);
        const y = py(point.value);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
      // Dots mark the days this series actually observed, so a reader can see
      // where the evidence is rather than inferring it from a smooth line -
      // and a one-point stroke renders as exactly one dot and no line.
      ctx.fillStyle = entry.color;
      stroke.points.forEach((point) => {
        ctx.beginPath();
        ctx.arc(px(point.t), py(point.value), isIndex ? 2 : 2.4, 0, Math.PI * 2);
        ctx.fill();
      });
      ctx.restore();
    });
  });

  // x labels: the two real endpoints, never an interpolated tick.
  ctx.font = `500 12px ${fonts.mono}`;
  ctx.fillStyle = EXPORT_COLORS.textMuted;
  ctx.fillText(formatSeriesDay(isoDay(t0)), plotX, plotY + plotH + 26);
  ctx.textAlign = "right";
  ctx.fillText(formatSeriesDay(isoDay(t1)), plotX + plotW, plotY + plotH + 26);
  ctx.textAlign = "left";

  // --- legend -------------------------------------------------------------
  // EACH PLATFORM BY NAME, WITH WHAT ITS NUMBER IS. "Yuyu-Tei · Retail price"
  // and "SNKRDUNK · Current listing" are different claims about a card, and a
  // legend naming only the platforms - or worse, calling all three "Market
  // Price" - would put a shop's asking price and a marketplace's cheapest open
  // listing on one chart as if they were the same measurement.
  let legendX = 48;
  const legendY = plan.height - 66;
  plan.series.forEach((entry) => {
    ctx.strokeStyle = entry.color;
    ctx.lineWidth = 2.4;
    ctx.beginPath();
    ctx.moveTo(legendX, legendY - 4);
    ctx.lineTo(legendX + 20, legendY - 4);
    ctx.stroke();
    legendX += 28;

    ctx.font = `600 13px ${fonts.sans}`;
    ctx.fillStyle = EXPORT_COLORS.textPrimary;
    ctx.fillText(entry.label, legendX, legendY);
    legendX += ctx.measureText(entry.label).width;

    if (entry.instrument) {
      const suffix = ` · ${entry.instrument}`;
      ctx.font = `500 13px ${fonts.sans}`;
      ctx.fillStyle = EXPORT_COLORS.textMuted;
      ctx.fillText(suffix, legendX, legendY);
      legendX += ctx.measureText(suffix).width;
    }
    legendX += 26;
  });

  // --- footer -------------------------------------------------------------
  ctx.font = `500 11px ${fonts.sans}`;
  ctx.fillStyle = EXPORT_COLORS.textMuted;
  const notes = [plan.breakNote, plan.disclaimer].filter(Boolean).join("   ");
  ctx.fillText(notes, 48, plan.height - 30);

  ctx.textAlign = "right";
  ctx.font = `600 13px ${fonts.display}`;
  ctx.fillStyle = EXPORT_COLORS.parchment;
  ctx.fillText(plan.attribution, plan.width - 48, plan.height - 30);
  ctx.textAlign = "left";

  return canvas;
}

/** Render and hand the file to the reader.
 *
 * Never throws at the call site - see `downloadCanvasPng`. The caller shows a
 * quiet message instead of the page dying inside a click handler.
 */
export async function downloadPrintChartExport(
  plan: PrintExportPlan,
  options: { fonts?: ExportFonts; document?: Document } = {},
): Promise<boolean> {
  const doc = options.document ?? document;
  try {
    const canvas = renderPrintChartExport(plan, { ...options, document: doc });
    return await downloadCanvasPng(canvas, plan.filename, doc);
  } catch {
    return false;
  }
}
