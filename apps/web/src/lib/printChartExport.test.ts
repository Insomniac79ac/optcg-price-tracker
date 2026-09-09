/** What the exact-print PNG export is allowed to claim.
 *
 * These assert the PLAN, not pixels: jsdom has no 2D context, and the plan is
 * where every honesty rule actually lives. A canvas that painted the plan
 * wrongly would be a rendering bug; a plan that carried a number the server
 * never sent would be a lie, and that is what is worth pinning.
 */

import { describe, expect, it } from "vitest";

import {
  buildPrintChartExport,
  printExportFilename,
  type PrintExportIdentity,
} from "./printChartExport";
import { safeFilenameToken } from "./chartExport";
import type { PrintAnalytics, PrintAnalyticsHeadline } from "./printAnalytics";
import type { PrintSeries, PrintSeriesPoint } from "./printSeries";

const IDENTITY: PrintExportIdentity = {
  cardCode: "OP01-001",
  displayName: "Roronoa Zoro",
  printingLabel: "Alt Art",
  releaseCode: "OP-01",
};

const NOW = new Date("2026-09-09T10:00:00Z");

function point(day: string, value: number | null, over: Partial<PrintSeriesPoint> = {}) {
  return {
    t: `${day}T20:00:00Z`,
    day,
    value_jpy: value,
    reference_type: null,
    evidence_type: null,
    eligible: null,
    constraint: null,
    ineligible_reason: null,
    sample_size: null,
    observations_in_day: null,
    index_version: 3,
    source_semantics_version: 2,
    source_count: 1,
    coverage_status: "full",
    source_price_range_low_jpy: null,
    source_price_range_high_jpy: null,
    ...over,
  } as unknown as PrintSeriesPoint;
}

function series(
  key: string,
  source: string | null,
  segments: { referenceType?: string | null; points: PrintSeriesPoint[] }[],
  over: Partial<PrintSeries> = {},
): PrintSeries {
  return {
    key,
    kind: source ? "source" : "market_index",
    source,
    role: "primary",
    available: true,
    unavailable_reason: null,
    segments: segments.map((segment) => ({
      reference_type: segment.referenceType ?? (source ? "retail_sell" : null),
      evidence_type: source ? "listing" : null,
      index_version: 3,
      source_semantics_version: 2,
      points: segment.points,
    })),
    breaks: [],
    coverage: {
      earliest: null,
      latest: null,
      distinct_days: 0,
      point_count: 0,
      covers_7d: null,
      covers_30d: null,
    },
    ...over,
  } as unknown as PrintSeries;
}

function headline(over: Partial<PrintAnalyticsHeadline> = {}): PrintAnalyticsHeadline {
  return {
    current_value_jpy: 22900,
    current_as_of: "2026-09-08",
    starting_value_jpy: 27400,
    starting_as_of: "2026-08-21",
    // Deliberately NOT the maximum of the plotted points below: a client
    // recomputing the high from the chart would get 24000.
    high_value_jpy: 27400,
    high_as_of: "2026-08-21",
    low_value_jpy: 22650,
    low_as_of: "2026-09-01",
    change: null,
    change_unavailable_reason: "index_version_change",
    observed_days: 19,
    coverage_status: "full",
    ...over,
  };
}

function analytics(over: Partial<PrintAnalytics> = {}): PrintAnalytics {
  return {
    card_print_id: 1,
    requested_window: "all",
    window_start: null,
    default_window: "all",
    generated_at: "2026-09-09T08:00:00Z",
    windows: [
      { token: "2w", available: true, covered_days: 33, required_days: 14 },
      { token: "all", available: true, covered_days: 33, required_days: null },
    ],
    headline: headline(),
    series: [
      series("market_index", null, [
        { points: [point("2026-09-06", 23000), point("2026-09-07", 23500)] },
      ]),
      series("source:yuyutei", "yuyutei", [
        { points: [point("2026-09-06", 24000), point("2026-09-07", 23800)] },
      ]),
      series("source:snkrdunk", "snkrdunk", [
        {
          referenceType: "listing_floor",
          points: [point("2026-09-06", 21000), point("2026-09-07", 21200)],
        },
      ]),
    ],
    ...over,
  };
}

describe("what the export represents", () => {
  it("names the exact print, not just the card code", () => {
    const plan = buildPrintChartExport(analytics(), IDENTITY, { now: NOW })!;

    expect(plan.title).toBe("Roronoa Zoro");
    expect(plan.subtitle).toContain("OP01-001");
    expect(plan.subtitle).toContain("Alt Art");
    // A card code is a family name - 955 codes carry more than one print - so
    // the print id is on the file too.
    expect(plan.printRef).toBe("#1");
  });

  it("carries the window the reader was actually looking at", () => {
    const plan = buildPrintChartExport(
      analytics({ requested_window: "2w" }),
      IDENTITY,
      { now: NOW },
    )!;

    expect(plan.windowToken).toBe("2w");
    expect(plan.windowLabel).toBe("2W");
    expect(plan.filename).toContain("-2w-");
  });

  it("names each platform and what its number is, never generically", () => {
    const plan = buildPrintChartExport(analytics(), IDENTITY, { now: NOW })!;
    const labels = plan.series.map((entry) => entry.label);

    expect(labels).toContain("Market Index");
    expect(labels).toContain("Yuyu-Tei");
    expect(labels).toContain("SNKRDUNK");
    // The three are not the same kind of number and the file must not imply
    // they are.
    expect(labels).not.toContain("Market Price");
    expect(JSON.stringify(plan)).not.toMatch(/market price/i);

    // The legend keeps the SERVER's order - the same order as the chips above
    // the chart. Paint order (index last, on top) is the renderer's business.
    expect(labels).toEqual(["Market Index", "Yuyu-Tei", "SNKRDUNK"]);

    const yuyu = plan.series.find((entry) => entry.label === "Yuyu-Tei")!;
    const snkr = plan.series.find((entry) => entry.label === "SNKRDUNK")!;
    const index = plan.series.find((entry) => entry.label === "Market Index")!;
    expect(yuyu.instrument).toBe("Retail price");
    expect(snkr.instrument).toBe("Current listing");
    // The index is not quoted by anyone, so it carries no instrument.
    expect(index.instrument).toBeNull();
  });

  it("omits a platform with no history rather than drawing it flat", () => {
    // Print 5686's shape: SNKRDUNK only.
    const plan = buildPrintChartExport(
      analytics({
        series: [
          series("market_index", null, [
            { points: [point("2026-09-06", 13000), point("2026-09-07", 13000)] },
          ]),
          series("source:snkrdunk", "snkrdunk", [
            {
              referenceType: "listing_floor",
              points: [point("2026-09-06", 13000), point("2026-09-07", 13000)],
            },
          ]),
        ],
      }),
      IDENTITY,
      { now: NOW },
    )!;

    const labels = plan.series.map((entry) => entry.label);
    expect(labels).toContain("SNKRDUNK");
    // Absent, not a zero line and not a "no data" rail - and no legend entry
    // for a line that is not there.
    expect(labels).not.toContain("Yuyu-Tei");
    expect(JSON.stringify(plan)).not.toContain("Yuyu-Tei");
  });

  it("drops a platform whose every reading is disqualified", () => {
    // Present in the payload, but nothing on the line: a legend entry here
    // would assert a line the picture does not contain.
    const plan = buildPrintChartExport(
      analytics({
        series: [
          series("market_index", null, [
            { points: [point("2026-09-06", 13000), point("2026-09-07", 13000)] },
          ]),
          series("source:snkrdunk", "snkrdunk", [
            {
              referenceType: "listing_floor",
              points: [
                point("2026-09-06", 1000, { eligible: false, constraint: "platform_floor" }),
                point("2026-09-07", 1000, { eligible: false, constraint: "platform_floor" }),
              ],
            },
          ]),
        ],
      }),
      IDENTITY,
      { now: NOW },
    )!;

    expect(plan.series.map((entry) => entry.label)).toEqual(["Market Index"]);
  });
});

describe("gaps and breaks survive the export", () => {
  it("keeps two server segments as two strokes with no path between them", () => {
    const plan = buildPrintChartExport(
      analytics({
        series: [
          series("market_index", null, [
            { points: [point("2026-09-01", 20000), point("2026-09-02", 20100)] },
            { points: [point("2026-09-03", 22000), point("2026-09-04", 22100)] },
          ]),
        ],
      }),
      IDENTITY,
      { now: NOW },
    )!;

    const index = plan.series.find((entry) => entry.label === "Market Index")!;
    expect(index.strokes).toHaveLength(2);
    // No stroke spans the boundary, so there is nothing to draw across it.
    expect(index.strokes[0].points.map((p) => p.value)).toEqual([20000, 20100]);
    expect(index.strokes[1].points.map((p) => p.value)).toEqual([22000, 22100]);
    expect(index.strokes.every((stroke) => stroke.points.length === 2)).toBe(true);
  });

  it("ends a run at a non-plottable point instead of bridging it", () => {
    const plan = buildPrintChartExport(
      analytics({
        series: [
          series("market_index", null, [
            {
              points: [
                point("2026-09-01", 20000),
                // A day on which no source was eligible. Never a zero, and
                // never joined across.
                point("2026-09-02", null),
                point("2026-09-03", 21000),
              ],
            },
          ]),
        ],
      }),
      IDENTITY,
      { now: NOW },
    )!;

    const index = plan.series.find((entry) => entry.label === "Market Index")!;
    expect(index.strokes).toHaveLength(2);
    expect(index.strokes.flatMap((s) => s.points.map((p) => p.value))).toEqual([20000, 21000]);
    // The null day is nowhere in the file - not as 0, not interpolated.
    expect(JSON.stringify(plan)).not.toContain('"value":0');
  });

  it("carries the server's break markers and says lines are not joined", () => {
    const broken = series("market_index", null, [
      { points: [point("2026-09-01", 20000)] },
      { points: [point("2026-09-03", 22000), point("2026-09-04", 22100)] },
    ]);
    (broken as unknown as { breaks: unknown[] }).breaks = [
      { at: "2026-09-03T00:00:00Z", reason: "index_version_change" },
    ];

    const plan = buildPrintChartExport(analytics({ series: [broken] }), IDENTITY, { now: NOW })!;

    expect(plan.breaks.length).toBeGreaterThan(0);
    expect(plan.breakNote).toMatch(/not joined across them/i);
  });
});

describe("the headline is the server's", () => {
  it("formats the response's own figures and derives none of them", () => {
    const plan = buildPrintChartExport(analytics(), IDENTITY, { now: NOW })!;

    expect(plan.current).toBe("￥22,900");
    expect(plan.currentAsOf).toBe("Sep 8, 2026");
    expect(plan.start).toBe("￥27,400");
    expect(plan.high).toBe("￥27,400");
    expect(plan.low).toBe("￥22,650");
    expect(plan.observedDays).toBe(19);
    // The plotted points top out at ￥24,000. A client deriving the high from
    // them would print that; the server's 27,400 is what must be in the file.
    expect(plan.high).not.toBe("￥24,000");
  });

  it("prints the server's refusal rather than computing a change", () => {
    const plan = buildPrintChartExport(analytics(), IDENTITY, { now: NOW })!;

    expect(plan.absoluteChange).toBeNull();
    expect(plan.pctChange).toBeNull();
    expect(plan.changeUnavailable).toMatch(/changed how the Market Index is calculated/i);
  });

  it("publishes a change exactly as the server signed it", () => {
    const plan = buildPrintChartExport(
      analytics({
        headline: headline({
          change: {
            absolute_jpy: -4500,
            pct: -16.42,
            from_date: "2026-08-21",
            to_date: "2026-09-08",
            spans_break: true,
          },
          change_unavailable_reason: null,
        }),
      }),
      IDENTITY,
      { now: NOW },
    )!;

    expect(plan.absoluteChange).toBe("−￥4,500");
    expect(plan.pctChange).toBe("−16.42%");
    expect(plan.spansBreak).toBe(true);
    expect(plan.changeUnavailable).toBeNull();
  });

  it("carries no average, sales, volume or sample-size claim", () => {
    const serialised = JSON.stringify(
      buildPrintChartExport(analytics(), IDENTITY, { now: NOW }),
    );

    // `observedDays` counts days Atlas archived a number. Nothing recorded
    // anywhere in Atlas is a transaction, and there is no average because the
    // only combination rule the system owns is a same-day median.
    expect(serialised).not.toMatch(/average|mean\b|sales|traded|trades|volume|sample/i);
  });
});

describe("branding and the file itself", () => {
  it("asks for the watermark, the attribution and a disclaimer", () => {
    const plan = buildPrintChartExport(analytics(), IDENTITY, { now: NOW })!;

    expect(plan.watermark).toBe(true);
    expect(plan.attribution).toBe("CardPirate");
    expect(plan.disclaimer).toMatch(/not investment advice/i);
    // Self-contained and opaque: its own ground, not the page's.
    expect(plan.background).toMatch(/^#/);
  });

  it("uses the Index export's proven dimensions and 2x strategy", () => {
    const plan = buildPrintChartExport(analytics(), IDENTITY, { now: NOW })!;

    expect(plan.width).toBe(1200);
    expect(plan.height).toBe(675);
    expect(plan.scale).toBe(2);
  });

  it("builds a deterministic, safe filename", () => {
    expect(printExportFilename("OP01-001", 1, "all", NOW)).toBe(
      "card-pirate-op01-001-1-all-2026-09-09.png",
    );
    // Same inputs, same name.
    expect(printExportFilename("OP01-001", 1, "all", NOW)).toBe(
      printExportFilename("OP01-001", 1, "all", NOW),
    );
  });

  it("neutralises anything that could travel into a path", () => {
    const name = printExportFilename("../../etc/passwd", "9 9", "2W /../", NOW);

    expect(name).not.toContain("/");
    expect(name).not.toContain("..");
    expect(name).toMatch(/^card-pirate-[a-z0-9-]+\.png$/);
    expect(safeFilenameToken("", "fallback")).toBe("fallback");
    expect(safeFilenameToken("!!!", "fallback")).toBe("fallback");
  });
});

describe("when there is nothing to draw", () => {
  it("returns null rather than a picture of an empty axis", () => {
    expect(buildPrintChartExport(null, IDENTITY, { now: NOW })).toBeNull();
    expect(
      buildPrintChartExport(analytics({ series: [] }), IDENTITY, { now: NOW }),
    ).toBeNull();
    expect(
      buildPrintChartExport(
        analytics({
          series: [series("market_index", null, [{ points: [point("2026-09-01", null)] }])],
        }),
        IDENTITY,
        { now: NOW },
      ),
    ).toBeNull();
  });
});
