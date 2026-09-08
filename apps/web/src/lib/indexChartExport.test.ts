/** What the downloaded PNG is allowed to say.
 *
 * The rasterisation itself is untestable here - jsdom has no 2D context - so
 * everything that could make the file DISHONEST is decided in the plan and
 * asserted against the plan: that the headline strings are the server's own,
 * that a snapshot gap survives as a separate dashed segment rather than being
 * stroked as a daily line, that no point is invented between two real ones,
 * and that an empty window produces no file at all. Same division the chart's
 * own geometry already keeps in cardPirateIndex.test.ts.
 */

import { describe, expect, it } from "vitest";

import type { IndexBreak, IndexPoint, IndexSeries, IndexWindowRow } from "./cardPirateIndex";
import {
  DEFAULT_EXPORT_FONTS,
  EXPORT_COLORS,
  buildIndexExport,
  indexExportFilename,
  resolveExportFonts,
} from "./indexChartExport";

const NOW = new Date("2026-09-08T11:20:00Z");

function point(partial: Partial<IndexPoint> & { date: string; value: string }): IndexPoint {
  return {
    is_base: false,
    prior_point_date: null,
    step_days: 1,
    chain_link_log_return: null,
    constituent_count: 296,
    eligible_print_count: 305,
    movers_up: 0,
    movers_down: 0,
    movers_flat: 296,
    capped_count: 0,
    ...partial,
  };
}

const WINDOWS: IndexWindowRow[] = [
  { token: "2w", available: false, covered_days: 5, required_days: 14 },
  { token: "1m", available: false, covered_days: 5, required_days: 30 },
  { token: "3m", available: false, covered_days: 5, required_days: 90 },
  { token: "6m", available: false, covered_days: 5, required_days: 180 },
  { token: "1y", available: false, covered_days: 5, required_days: 365 },
  { token: "2y", available: false, covered_days: 5, required_days: 730 },
  { token: "all", available: true, covered_days: 5, required_days: null },
];

/** Staging's real five-day archive. */
const FIVE_DAYS: IndexPoint[] = [
  point({ date: "2026-09-03", value: "1000.0000", is_base: true, step_days: null }),
  point({ date: "2026-09-04", value: "1000.4210" }),
  point({ date: "2026-09-05", value: "1000.9577" }),
  point({ date: "2026-09-06", value: "1000.3300" }),
  point({ date: "2026-09-07", value: "1000.1065" }),
];

function series(partial: Partial<IndexSeries> = {}): IndexSeries {
  return {
    scope_kind: "overall",
    scope_key: "",
    methodology_version: 1,
    index_version: 3,
    source_semantics_version: 2,
    requested_window: "all",
    window_start: null,
    available_from: "2026-09-03",
    available_to: "2026-09-07",
    covers_requested_window: true,
    points: FIVE_DAYS,
    starting_value: "1000.0000",
    current_value: "1000.1065",
    low_value: "1000.0000",
    high_value: "1000.9577",
    change: {
      absolute: "0.1065",
      pct: "0.010650",
      from_date: "2026-09-03",
      to_date: "2026-09-07",
      spans_break: false,
    },
    change_unavailable_reason: null,
    windows: WINDOWS,
    default_window: "all",
    breaks: [],
    ...partial,
  };
}

function breakEntry(partial: Partial<IndexBreak> & { at: string; reason: string }): IndexBreak {
  return {
    from_methodology_version: null,
    to_methodology_version: null,
    from_index_version: null,
    to_index_version: null,
    from_source_semantics_version: null,
    to_source_semantics_version: null,
    carried: null,
    carried_level: null,
    carried_from_point_date: null,
    prior_point_date: null,
    step_days: null,
    ...partial,
  };
}

// --- A. the filename ---------------------------------------------------------

describe("the generated filename names the chart and the day", () => {
  it("is card-pirate-index-<window>-<YYYY-MM-DD>.png", () => {
    expect(indexExportFilename("all", NOW)).toBe("card-pirate-index-all-2026-09-08.png");
    expect(indexExportFilename("3m", NOW)).toBe("card-pirate-index-3m-2026-09-08.png");
  });

  it("takes the window from the response, not from a caller's guess", () => {
    const plan = buildIndexExport(series({ requested_window: "1y" }), { now: NOW });
    expect(plan?.filename).toBe("card-pirate-index-1y-2026-09-08.png");
  });

  it("never lets an unexpected token travel into a path", () => {
    expect(indexExportFilename("../../etc/passwd", NOW)).toBe(
      "card-pirate-index-etc-passwd-2026-09-08.png",
    );
    expect(indexExportFilename("3M", NOW)).toBe("card-pirate-index-3m-2026-09-08.png");
    expect(indexExportFilename("!!!", NOW)).toBe("card-pirate-index-window-2026-09-08.png");
  });
});

// --- B. the active window is what gets exported ------------------------------

describe("the plan is about the window on screen", () => {
  it("carries the response's own window token and its display label", () => {
    const plan = buildIndexExport(series(), { now: NOW });
    expect(plan?.windowToken).toBe("all");
    expect(plan?.windowLabel).toBe("All");
  });

  it("exports a future 3m response as 3m, with only that response's points", () => {
    const threeMonth = series({
      requested_window: "3m",
      window_start: "2026-06-09",
      points: FIVE_DAYS.slice(2),
    });
    const plan = buildIndexExport(threeMonth, { now: NOW });
    expect(plan?.windowToken).toBe("3m");
    expect(plan?.windowLabel).toBe("3M");
    // Exactly the three points it was handed - nothing sliced, nothing added.
    expect(plan?.segments.flatMap((s) => s.points.map((p) => p.date))).toEqual([
      "2026-09-05",
      "2026-09-06",
      "2026-09-07",
    ]);
  });

  it("does not fall back to the surface default when a window is selected", () => {
    const plan = buildIndexExport(
      series({ requested_window: "1y", default_window: "3m" }),
      { now: NOW },
    );
    expect(plan?.windowToken).toBe("1y");
  });
});

// --- C. every figure is the server's -----------------------------------------

describe("the headline values come from the current response", () => {
  it("uses the response's level, start, high and low verbatim", () => {
    const plan = buildIndexExport(series(), { now: NOW });
    expect(plan?.level).toBe("1,000.11");
    expect(plan?.start).toBe("1,000.00");
    expect(plan?.high).toBe("1,000.96");
    expect(plan?.low).toBe("1,000.00");
  });

  it("uses the server's change, not one derived from the points", () => {
    // The points run 1000.0000 -> 1000.1065, but the assertion is that the
    // plan echoes `change`, so a response whose change disagrees with its own
    // points must still export the change.
    const plan = buildIndexExport(
      series({
        change: {
          absolute: "-2.5000",
          pct: "-0.250000",
          from_date: "2026-09-03",
          to_date: "2026-09-07",
          spans_break: false,
        },
      }),
      { now: NOW },
    );
    expect(plan?.absoluteChange).toBe("−2.50");
    expect(plan?.pctChange).toBe("−0.25%");
  });

  it("keeps percent in the units the server publishes", () => {
    const plan = buildIndexExport(series(), { now: NOW });
    // 0.010650 is 0.01 %, not 1.07 %.
    expect(plan?.pctChange).toBe("+0.01%");
  });

  it("carries the linked marker when the span crosses a break", () => {
    const plan = buildIndexExport(
      series({
        change: {
          absolute: "0.1065",
          pct: "0.010650",
          from_date: "2026-09-03",
          to_date: "2026-09-07",
          spans_break: true,
        },
      }),
      { now: NOW },
    );
    expect(plan?.spansBreak).toBe(true);
  });

  it("carries the covered range the server published", () => {
    const plan = buildIndexExport(series(), { now: NOW });
    expect(plan?.coveredRange).toBe("Sep 3 – Sep 7, 2026");
  });
});

// --- D. honest absence -------------------------------------------------------

describe("an absent change is exported as an absence", () => {
  it("says so in words and prints no number", () => {
    const plan = buildIndexExport(series({ change: null }), { now: NOW });
    expect(plan?.changeUnavailable).toBe("Change not available across this period");
    expect(plan?.absoluteChange).toBeNull();
    expect(plan?.pctChange).toBeNull();
  });

  it("never substitutes a zero for a null change", () => {
    const plan = buildIndexExport(series({ change: null }), { now: NOW });
    expect(plan?.absoluteChange).not.toBe("0.00");
    expect(plan?.pctChange).not.toBe("0.00%");
  });

  it("produces NO plan at all when the window holds no published point", () => {
    // The button is disabled off this null. Exporting an empty frame with a
    // headline on it would be a picture of a chart that does not exist.
    expect(buildIndexExport(series({ points: [] }), { now: NOW })).toBeNull();
  });

  it("flags a partial window rather than padding it", () => {
    const plan = buildIndexExport(
      series({ requested_window: "2y", covers_requested_window: false }),
      { now: NOW },
    );
    expect(plan?.partialHistory).toBe(true);
    // Five points in, five points out - a 2y request does not become 730 days.
    expect(plan?.segments.flatMap((s) => s.points).length).toBe(5);
  });
});

// --- E. gaps and breaks survive the export -----------------------------------

describe("chart honesty survives rasterisation", () => {
  const GAPPED: IndexPoint[] = [
    point({ date: "2026-09-03", value: "1000.0000", is_base: true, step_days: null }),
    point({ date: "2026-09-04", value: "1000.4210" }),
    // Three days missing from the archive.
    point({ date: "2026-09-07", value: "1000.1065", step_days: 3 }),
  ];

  it("splits a snapshot gap into its own dashed segment", () => {
    const plan = buildIndexExport(series({ points: GAPPED }), { now: NOW });
    const kinds = plan!.segments.map((s) => s.kind);
    expect(kinds).toEqual(["run", "gap", "run"]);
  });

  it("spans the gap between the two REAL endpoints and invents nothing between", () => {
    const plan = buildIndexExport(series({ points: GAPPED }), { now: NOW });
    const gap = plan!.segments.find((s) => s.kind === "gap")!;
    expect(gap.points.map((p) => p.date)).toEqual(["2026-09-04", "2026-09-07"]);
    // Every date in the plan is a date the response published. No 09-05, no
    // 09-06, no interpolation the screen does not draw either.
    const exported = plan!.segments.flatMap((s) => s.points.map((p) => p.date));
    const published = new Set(GAPPED.map((p) => p.date));
    for (const date of exported) expect(published.has(date)).toBe(true);
  });

  it("draws a contiguous window as one solid run", () => {
    const plan = buildIndexExport(series(), { now: NOW });
    expect(plan!.segments.map((s) => s.kind)).toEqual(["run"]);
    expect(plan!.segments[0].points).toHaveLength(5);
  });

  it("marks a methodology break from the server's breaks, never from the points", () => {
    const plan = buildIndexExport(
      series({
        breaks: [breakEntry({ at: "2026-09-05", reason: "index_version_change", carried: true })],
      }),
      { now: NOW },
    );
    expect(plan!.breaks).toHaveLength(1);
    expect(plan!.breaks[0].at).toBe("2026-09-05");
    expect(plan!.breaks[0].label).toContain("Methodology change");
  });

  it("does not draw a snapshot gap a second time as a methodology marker", () => {
    // The dashed segment already carries it; a break marker would claim the
    // measurement changed, which a cadence fact is not.
    const plan = buildIndexExport(
      series({
        points: GAPPED,
        breaks: [breakEntry({ at: "2026-09-07", reason: "snapshot_gap", step_days: 3 })],
      }),
      { now: NOW },
    );
    expect(plan!.breaks).toHaveLength(0);
    expect(plan!.segments.some((s) => s.kind === "gap")).toBe(true);
  });

  it("uses the same y-domain the screen used, so a flat index stays flat", () => {
    const plan = buildIndexExport(series(), { now: NOW });
    const [lo, hi] = plan!.yDomain;
    // Section 13.3: at least +/-1 % around the 1000 base, not a fitted axis
    // over the 0.96-point real range.
    expect(lo).toBeLessThanOrEqual(990);
    expect(hi).toBeGreaterThanOrEqual(1010);
  });
});

// --- F. self-contained and branded -------------------------------------------

describe("the file stands on its own", () => {
  it("carries the title, the brand mark and an attribution", () => {
    const plan = buildIndexExport(series(), { now: NOW });
    expect(plan?.title).toBe("Card Pirate Index");
    expect(plan?.watermark).toBe(true);
    expect(plan?.attribution).toBe("CardPirate");
  });

  it("paints its own opaque background rather than borrowing the page's", () => {
    const plan = buildIndexExport(series(), { now: NOW });
    expect(plan?.background).toBe(EXPORT_COLORS.background);
    expect(plan?.background).toMatch(/^#[0-9a-f]{6}$/i);
  });

  it("keeps the methodology's own disclaimer on the image", () => {
    const plan = buildIndexExport(series(), { now: NOW });
    expect(plan?.disclaimer).toContain("Not a price");
  });

  it("has fixed pixel dimensions that do not depend on the page layout", () => {
    const plan = buildIndexExport(series(), { now: NOW });
    expect(plan?.width).toBe(1200);
    expect(plan?.height).toBe(675);
    expect(plan?.scale).toBe(2);
  });
});

// --- G. fonts ----------------------------------------------------------------

describe("font resolution degrades rather than failing", () => {
  it("falls back to the generic stacks with no element to read", () => {
    expect(resolveExportFonts(null)).toEqual(DEFAULT_EXPORT_FONTS);
  });

  it("reads the page's own families when they are set", () => {
    const el = document.createElement("div");
    el.style.setProperty("--font-display", "__Fraunces_abc123");
    document.body.appendChild(el);
    expect(resolveExportFonts(el).display).toBe("__Fraunces_abc123");
    document.body.removeChild(el);
  });
});
