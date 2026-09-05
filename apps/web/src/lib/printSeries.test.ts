/** What the multi-series chart is allowed to draw and to say.
 *
 * These are behaviour tests for the decisions in printSeries.ts. The
 * invariants that matter are the ones a chart can silently violate without
 * anyone noticing: a line stroked across a methodology break, a constrained
 * ¥1,000 plotted as a price, a null archived index rendered as ¥0, a single
 * observation joined to nothing and drawn as a trend, a stored `price_type`
 * leaking into a client decision. Each is asserted on the chart model, which
 * is where every one of those decisions is actually made.
 */

import { describe, expect, it } from "vitest";

import {
  buildSeriesChartModel,
  dayToTime,
  instrumentLabel,
  isDefaultSelected,
  seriesDisplayLabel,
  seriesPaintOrder,
  seriesPlatformLabel,
  selectableSeries,
  PRINT_SERIES_WINDOWS,
  DEFAULT_PRINT_SERIES_WINDOW,
  type PrintSeries,
  type PrintSeriesHistory,
  type PrintSeriesPoint,
  type PrintSeriesSegment,
} from "./printSeries";

function point(day: string, valueJpy: number | null, extra: Partial<PrintSeriesPoint> = {}): PrintSeriesPoint {
  return {
    t: `${day}T02:00:00Z`,
    day,
    value_jpy: valueJpy,
    ...extra,
  };
}

function segment(
  points: PrintSeriesPoint[],
  overrides: Partial<PrintSeriesSegment> = {},
): PrintSeriesSegment {
  return {
    reference_type: null,
    evidence_type: null,
    index_version: null,
    source_semantics_version: null,
    points,
    ...overrides,
  };
}

function series(overrides: Partial<PrintSeries> & Pick<PrintSeries, "key" | "kind">): PrintSeries {
  const segments = overrides.segments ?? [];
  const points = segments.flatMap((entry) => entry.points);
  return {
    source: null,
    role: "primary",
    available: points.length > 0,
    unavailable_reason: points.length > 0 ? null : "no_history_in_window",
    breaks: [],
    coverage: {
      earliest: points[0]?.t ?? null,
      latest: points[points.length - 1]?.t ?? null,
      distinct_days: new Set(points.map((p) => p.day)).size,
      point_count: points.length,
      covers_7d: null,
      covers_30d: null,
    },
    segments,
    ...overrides,
  };
}

function marketIndex(segments: PrintSeriesSegment[], breaks: PrintSeries["breaks"] = []): PrintSeries {
  return series({ key: "market_index", kind: "market_index", segments, breaks });
}

function sourceSeries(
  name: string,
  segments: PrintSeriesSegment[],
  breaks: PrintSeries["breaks"] = [],
): PrintSeries {
  return series({ key: `source:${name}`, kind: "source", source: name, segments, breaks });
}

function history(entries: PrintSeries[], overrides: Partial<PrintSeriesHistory> = {}): PrintSeriesHistory {
  return {
    card_print_id: 11,
    window: "30d",
    window_start: "2026-08-06T00:00:00Z",
    generated_at: "2026-09-05T00:00:00Z",
    series: entries,
    ...overrides,
  };
}

const RETAIL = { reference_type: "retail_sell", evidence_type: "listing" };
const FLOOR = { reference_type: "listing_floor", evidence_type: "listing" };
const MEDIAN = { reference_type: "transaction_median", evidence_type: "transaction" };

function allKeys(payload: PrintSeriesHistory): Set<string> {
  return new Set(selectableSeries(payload).filter(isDefaultSelected).map((entry) => entry.key));
}

describe("A. three platforms on one chart", () => {
  const payload = history([
    marketIndex([
      segment(
        [point("2026-09-01", 4100), point("2026-09-02", 4150)],
        { index_version: 3, source_semantics_version: 2 },
      ),
    ]),
    sourceSeries("yuyutei", [
      segment([point("2026-09-01", 3980, RETAIL), point("2026-09-02", 4280, RETAIL)], RETAIL),
    ]),
    sourceSeries("snkrdunk", [
      segment([point("2026-09-01", 4300, FLOOR), point("2026-09-02", 4020, FLOOR)], FLOOR),
    ]),
  ]);

  it("keeps Market Index, Yuyu-Tei and SNKRDUNK independently identifiable", () => {
    const model = buildSeriesChartModel(payload, allKeys(payload));

    expect(model.series.map((entry) => entry.label)).toEqual([
      "Market Index",
      "Yuyu-Tei · Retail price",
      "SNKRDUNK · Current listing",
    ]);
    // Three series, three key spaces - nothing shares a dataKey, so no two
    // platforms can ever be stroked as one line.
    const dataKeys = model.series.flatMap((entry) => entry.strokes.map((s) => s.dataKey));
    expect(new Set(dataKeys).size).toBe(3);
    expect(model.hasLine).toBe(true);
  });

  it("puts all three on one row per day so they can be read against each other", () => {
    const model = buildSeriesChartModel(payload, allKeys(payload));

    expect(model.rows).toHaveLength(2);
    expect(model.rows[0].t).toBe(dayToTime("2026-09-01"));
    expect(model.rows[0].detail.map((d) => d.valueJpy).sort()).toEqual([3980, 4100, 4300]);
  });

  it("selects Market Index and every available primary source by default", () => {
    expect([...allKeys(payload)]).toEqual([
      "market_index",
      "source:yuyutei",
      "source:snkrdunk",
    ]);
  });

  it("does not label Market Index as a source or give it a platform instrument", () => {
    const model = buildSeriesChartModel(payload, allKeys(payload));
    const index = model.series.find((entry) => entry.kind === "market_index")!;

    expect(index.label).toBe("Market Index");
    expect(index.source).toBeNull();
    // Not "Market Index · Retail price", and not "Market Index · something".
    expect(index.label).not.toMatch(/·/);
  });
});

describe("B. platform deselection and reselection", () => {
  const payload = history([
    marketIndex([segment([point("2026-09-01", 4100), point("2026-09-02", 4150)])]),
    sourceSeries("yuyutei", [
      segment([point("2026-09-01", 3980, RETAIL), point("2026-09-02", 4280, RETAIL)], RETAIL),
    ]),
    sourceSeries("snkrdunk", [
      segment([point("2026-09-01", 4300, FLOOR), point("2026-09-02", 4020, FLOOR)], FLOOR),
    ]),
  ]);

  it("removes a deselected platform from the lines AND from the tooltip rows", () => {
    const model = buildSeriesChartModel(payload, new Set(["market_index", "source:yuyutei"]));

    expect(model.series.map((entry) => entry.key)).toEqual(["market_index", "source:yuyutei"]);
    // A platform off the chart must not survive in the tooltip - otherwise
    // turning it off hides the line and keeps the number.
    const labels = model.rows.flatMap((row) => row.detail.map((d) => d.label));
    expect(labels.some((label) => label.startsWith("SNKRDUNK"))).toBe(false);
  });

  it("brings it back unchanged when reselected", () => {
    const off = buildSeriesChartModel(payload, new Set(["market_index"]));
    const on = buildSeriesChartModel(payload, allKeys(payload));

    expect(off.series).toHaveLength(1);
    expect(on.series).toHaveLength(3);
    const snkrdunk = on.series.find((entry) => entry.source === "snkrdunk")!;
    expect(snkrdunk.strokes[0].points.map((p) => p.value_jpy)).toEqual([4300, 4020]);
  });

  it("charts a single platform on its own", () => {
    const model = buildSeriesChartModel(payload, new Set(["source:snkrdunk"]));

    expect(model.series.map((entry) => entry.label)).toEqual(["SNKRDUNK · Current listing"]);
    expect(model.hasPoints).toBe(true);
  });

  it("draws nothing at all when every platform is deselected", () => {
    const model = buildSeriesChartModel(payload, new Set<string>());

    expect(model.series).toEqual([]);
    expect(model.rows).toEqual([]);
    expect(model.hasPoints).toBe(false);
  });

  it("ignores a remembered key the current window does not carry", () => {
    // A chip dismissed at ALL must not resurrect a platform at 7D, and a key
    // for a platform that dropped out of this window must not invent one.
    const model = buildSeriesChartModel(payload, new Set(["source:cardrush", "market_index"]));

    expect(model.series.map((entry) => entry.key)).toEqual(["market_index"]);
  });
});

describe("C. windows", () => {
  it("offers 7d, 30d and all - and no 90d", () => {
    expect(PRINT_SERIES_WINDOWS).toEqual(["7d", "30d", "all"]);
    expect(PRINT_SERIES_WINDOWS).not.toContain("90d");
    expect(DEFAULT_PRINT_SERIES_WINDOW).toBe("30d");
  });

  it("charts exactly the points the requested window returned", () => {
    // The client never trims a payload to a narrower window of its own - a
    // 7d chart is a 7d REQUEST, so the model plots what came back verbatim.
    const wide = history(
      [
        sourceSeries("yuyutei", [
          segment(
            [
              point("2026-08-10", 3600, RETAIL),
              point("2026-09-01", 3980, RETAIL),
              point("2026-09-02", 4280, RETAIL),
            ],
            RETAIL,
          ),
        ]),
      ],
      { window: "all", window_start: null },
    );
    const narrow = history(
      [
        sourceSeries("yuyutei", [
          segment([point("2026-09-01", 3980, RETAIL), point("2026-09-02", 4280, RETAIL)], RETAIL),
        ]),
      ],
      { window: "7d" },
    );

    expect(buildSeriesChartModel(wide, allKeys(wide)).rows).toHaveLength(3);
    expect(buildSeriesChartModel(narrow, allKeys(narrow)).rows).toHaveLength(2);
  });
});

describe("D. an unknown future source", () => {
  const payload = history([
    sourceSeries("cardrush", [
      segment(
        [
          point("2026-09-01", 5100, { reference_type: "auction_high" }),
          point("2026-09-02", 5300, { reference_type: "auction_high" }),
        ],
        { reference_type: "auction_high", evidence_type: "transaction" },
      ),
    ]),
  ]);

  it("charts a platform this build has never heard of, named by the server", () => {
    const model = buildSeriesChartModel(payload, allKeys(payload));

    expect(model.series).toHaveLength(1);
    expect(model.series[0].label).toBe("cardrush · Auction high");
    expect(model.hasLine).toBe(true);
  });

  it("humanises an unknown instrument rather than guessing or dropping it", () => {
    expect(instrumentLabel("auction_high")).toBe("Auction high");
    expect(instrumentLabel(null)).toBeNull();
    expect(instrumentLabel("")).toBeNull();
  });

  it("names an unlabelled platform without inventing an instrument for it", () => {
    const unlabelled = history([
      sourceSeries("mercari", [segment([point("2026-09-01", 700), point("2026-09-02", 720)])]),
    ]);
    const model = buildSeriesChartModel(unlabelled, allKeys(unlabelled));

    expect(model.series[0].label).toBe("mercari");
    expect(seriesPlatformLabel(unlabelled.series[0])).toBe("mercari");
  });

  it("keeps the known instrument vocabulary the rest of the frontend uses", () => {
    expect(instrumentLabel("retail_sell")).toBe("Retail price");
    expect(instrumentLabel("listing_floor")).toBe("Current listing");
    expect(instrumentLabel("transaction_median")).toBe("Recent sales median");
  });
});

describe("E. thin history", () => {
  it("keeps a one-point series as one point and draws no line through it", () => {
    const payload = history([
      sourceSeries("yuyutei", [segment([point("2026-09-02", 3980, RETAIL)], RETAIL)]),
    ]);
    const model = buildSeriesChartModel(payload, allKeys(payload));

    expect(model.series[0].strokes).toHaveLength(1);
    expect(model.series[0].strokes[0].points).toHaveLength(1);
    expect(model.hasPoints).toBe(true);
    // A stroke of one point is a dot, not a trend - the chart says so.
    expect(model.hasLine).toBe(false);
  });

  it("gives an absent date no row at all rather than a carried-forward value", () => {
    const payload = history([
      sourceSeries("yuyutei", [
        segment(
          [
            point("2026-09-01", 3980, RETAIL),
            // 2026-09-02 is missing: the source did not report that day.
            point("2026-09-03", 4280, RETAIL),
          ],
          RETAIL,
        ),
      ]),
    ]);
    const model = buildSeriesChartModel(payload, allKeys(payload));

    expect(model.rows.map((row) => row.day)).toEqual(["2026-09-01", "2026-09-03"]);
    expect(model.rows.find((row) => row.day === "2026-09-02")).toBeUndefined();
    // No forward-fill, no ¥0, no interpolated point in the data.
    const values = model.rows.flatMap((row) => row.detail.map((d) => d.valueJpy));
    expect(values).toEqual([3980, 4280]);
    expect(values).not.toContain(0);
  });

  it("has nothing to chart when no series carries a point", () => {
    const payload = history([
      series({
        key: "market_index",
        kind: "market_index",
        available: false,
        unavailable_reason: "no_history_in_window",
      }),
      series({
        key: "source:snkrdunk",
        kind: "source",
        source: "snkrdunk",
        available: false,
        unavailable_reason: "source_not_configured",
      }),
    ]);

    // An unavailable series is not a chip - there is nothing to toggle.
    expect(selectableSeries(payload)).toEqual([]);
    const model = buildSeriesChartModel(payload, new Set(["market_index", "source:snkrdunk"]));
    expect(model.hasPoints).toBe(false);
    expect(model.rows).toEqual([]);
  });

  it("distinguishes an unconfigured source from a source with no price", () => {
    const payload = history([
      series({
        key: "source:cardmarket",
        kind: "source",
        source: "cardmarket",
        available: false,
        unavailable_reason: "source_not_configured",
      }),
    ]);

    // The reason survives on the payload; what it must NOT do is appear as a
    // live, empty chip that reads as "this platform has no price for the card".
    expect(payload.series[0].unavailable_reason).toBe("source_not_configured");
    expect(selectableSeries(payload)).toEqual([]);
  });

  it("charts nothing at all from a null payload", () => {
    const model = buildSeriesChartModel(null, new Set(["market_index"]));
    expect(model).toMatchObject({ series: [], rows: [], breaks: [], hasPoints: false });
    expect(selectableSeries(null)).toEqual([]);
  });
});

describe("F. Market Index methodology breaks", () => {
  const payload = history([
    marketIndex(
      [
        segment([point("2026-08-28", 3900), point("2026-08-29", 3950)], {
          index_version: 1,
          source_semantics_version: 1,
        }),
        segment([point("2026-08-30", 4200), point("2026-08-31", 4210)], {
          index_version: 2,
          source_semantics_version: 1,
        }),
        segment([point("2026-09-01", 4400), point("2026-09-02", 4450)], {
          index_version: 3,
          source_semantics_version: 2,
        }),
      ],
      [
        { at: "2026-08-30T20:00:00Z", reason: "index_version_change", from_index_version: 1, to_index_version: 2 },
        { at: "2026-09-01T20:00:00Z", reason: "index_version_change", from_index_version: 2, to_index_version: 3 },
        {
          at: "2026-09-01T20:00:00Z",
          reason: "source_semantics_version_change",
          from_source_semantics_version: 1,
          to_source_semantics_version: 2,
        },
      ],
    ),
  ]);

  it("never draws v1 -> v2 -> v3 as one uninterrupted line", () => {
    const model = buildSeriesChartModel(payload, allKeys(payload));
    const index = model.series[0];

    // Three strokes, three dataKeys. There is no path between them for the
    // renderer to stroke, whatever the values do.
    expect(index.strokes).toHaveLength(3);
    expect(new Set(index.strokes.map((s) => s.dataKey)).size).toBe(3);
    expect(index.strokes.map((s) => s.segmentIndex)).toEqual([0, 1, 2]);
  });

  it("puts each methodology segment's values under its own key on the shared rows", () => {
    const model = buildSeriesChartModel(payload, allKeys(payload));
    const [v1, v2, v3] = model.series[0].strokes.map((s) => s.dataKey);

    const aug29 = model.rows.find((row) => row.day === "2026-08-29")!;
    expect(aug29[v1]).toBe(3950);
    expect(aug29[v2]).toBeUndefined();
    expect(aug29[v3]).toBeUndefined();

    const sep01 = model.rows.find((row) => row.day === "2026-09-01")!;
    expect(sep01[v3]).toBe(4400);
    expect(sep01[v2]).toBeUndefined();
  });

  it("marks every break the server reported, on the chart's own day grid", () => {
    const model = buildSeriesChartModel(payload, allKeys(payload));

    expect(model.breaks).toHaveLength(3);
    expect(model.breaks.map((entry) => entry.t)).toEqual([
      dayToTime("2026-08-30"),
      dayToTime("2026-09-01"),
      dayToTime("2026-09-01"),
    ]);
    expect(model.breaks.map((entry) => entry.reason)).toEqual([
      "index_version_change",
      "index_version_change",
      "source_semantics_version_change",
    ]);
  });
});

describe("G. source instrument breaks", () => {
  it("never joins listing_floor to transaction_median as one instrument", () => {
    const payload = history([
      sourceSeries(
        "snkrdunk",
        [
          segment([point("2026-09-01", 4300, FLOOR), point("2026-09-02", 4250, FLOOR)], FLOOR),
          segment([point("2026-09-03", 3900, MEDIAN), point("2026-09-04", 3950, MEDIAN)], MEDIAN),
        ],
        [
          {
            at: "2026-09-03T02:00:00Z",
            reason: "reference_type_change",
            from_reference_type: "listing_floor",
            to_reference_type: "transaction_median",
          },
        ],
      ),
    ]);
    const model = buildSeriesChartModel(payload, allKeys(payload));
    const [snkrdunk] = model.series;

    expect(snkrdunk.strokes).toHaveLength(2);
    expect(snkrdunk.strokes[0].instrument).toBe("Current listing");
    expect(snkrdunk.strokes[1].instrument).toBe("Recent sales median");
    expect(model.breaks).toHaveLength(1);

    // Two instruments means the legend stops claiming one, rather than
    // labelling the listing half with the median's name or vice versa.
    expect(snkrdunk.label).toBe("SNKRDUNK");
  });

  it("keeps two unlabelled instruments apart rather than welding them", () => {
    // An unconfigured source reports reference_type null for every stored
    // price_type, so the server reports the boundary as instrument_change.
    // Unlabelled is not "the same".
    const payload = history([
      sourceSeries(
        "cardrush",
        [
          segment([point("2026-09-01", 800), point("2026-09-02", 810)]),
          segment([point("2026-09-03", 1500), point("2026-09-04", 1520)]),
        ],
        [{ at: "2026-09-03T02:00:00Z", reason: "instrument_change" }],
      ),
    ]);
    const model = buildSeriesChartModel(payload, allKeys(payload));

    expect(model.series[0].strokes).toHaveLength(2);
    expect(model.breaks[0].reason).toBe("instrument_change");
  });
});

describe("H. constrained and unrecorded observations", () => {
  it("never plots a constrained ¥1,000 floor, and never drops it either", () => {
    const payload = history([
      sourceSeries("snkrdunk", [
        segment(
          [
            point("2026-09-01", 4300, FLOOR),
            point("2026-09-02", 1000, {
              ...FLOOR,
              eligible: false,
              constraint: "platform_floor",
              ineligible_reason: "platform_floor",
            }),
            point("2026-09-03", 4200, FLOOR),
          ],
          FLOOR,
        ),
      ]),
    ]);
    const model = buildSeriesChartModel(payload, allKeys(payload));
    const [snkrdunk] = model.series;

    // Two strokes: the line is broken AT the constrained reading, so nothing
    // is drawn through ¥1,000 and the two market prices are not joined across
    // a day the source stopped reporting market evidence.
    expect(snkrdunk.strokes).toHaveLength(2);
    expect(snkrdunk.strokes[0].points.map((p) => p.value_jpy)).toEqual([4300]);
    expect(snkrdunk.strokes[1].points.map((p) => p.value_jpy)).toEqual([4200]);
    expect(snkrdunk.plottedCount).toBe(2);
    expect(snkrdunk.pointCount).toBe(3);

    // No stroke carries the ¥1,000 anywhere on the line...
    const constrainedRow = model.rows.find((row) => row.day === "2026-09-02")!;
    for (const stroke of snkrdunk.strokes) {
      expect(constrainedRow[stroke.dataKey]).toBeUndefined();
    }
    // ...and it is still available to the reader, marked as what it is.
    expect(constrainedRow.detail).toEqual([
      {
        seriesKey: "source:snkrdunk",
        label: "SNKRDUNK · Current listing",
        kind: "source",
        valueJpy: 1000,
        plotted: false,
        constraint: "platform_floor",
        coverageStatus: null,
      },
    ]);
  });

  it("draws no stroke at all for a wholly constrained platform", () => {
    const payload = history([
      sourceSeries("snkrdunk", [
        segment(
          [
            point("2026-09-01", 1000, { ...FLOOR, eligible: false, constraint: "platform_floor" }),
            point("2026-09-02", 1000, { ...FLOOR, eligible: false, constraint: "platform_floor" }),
          ],
          FLOOR,
        ),
      ]),
    ]);
    const model = buildSeriesChartModel(payload, allKeys(payload));

    expect(model.series[0].strokes).toEqual([]);
    expect(model.series[0].plottedCount).toBe(0);
    expect(model.hasPoints).toBe(false);
  });

  it("never renders an archived index with no value as ¥0", () => {
    const payload = history([
      marketIndex([
        segment(
          [
            point("2026-09-01", 4100, { index_version: 3, coverage_status: "full" }),
            // A recorded result: no source was eligible that day.
            point("2026-09-02", null, { index_version: 3, coverage_status: "none" }),
            point("2026-09-03", 4180, { index_version: 3, coverage_status: "full" }),
          ],
          { index_version: 3 },
        ),
      ]),
    ]);
    const model = buildSeriesChartModel(payload, allKeys(payload));
    const [index] = model.series;

    expect(index.strokes).toHaveLength(2);
    const values = model.rows.flatMap((row) =>
      index.strokes.map((stroke) => row[stroke.dataKey]).filter((v) => v !== undefined),
    );
    expect(values).toEqual([4100, 4180]);
    expect(values).not.toContain(0);

    const nullDay = model.rows.find((row) => row.day === "2026-09-02")!;
    expect(nullDay.detail[0]).toMatchObject({
      valueJpy: null,
      plotted: false,
      coverageStatus: "none",
    });
  });

  it("treats an unclassified point as plottable rather than disqualified", () => {
    // An API that never classified a point has not disqualified it.
    const payload = history([
      sourceSeries("yuyutei", [
        segment([point("2026-09-01", 3980, RETAIL), point("2026-09-02", 4280, RETAIL)], RETAIL),
      ]),
    ]);
    const model = buildSeriesChartModel(payload, allKeys(payload));

    expect(model.series[0].strokes).toHaveLength(1);
    expect(model.series[0].plottedCount).toBe(2);
  });
});

describe("I. what the client must never depend on", () => {
  it("makes no decision from a stored price_type", () => {
    // The server withholds price_type from every point on purpose (see
    // schemas.PrintSeriesPointOut). A `price_type` smuggled onto a point must
    // change nothing: labelling, segmentation and plotting all come from
    // reference_type/evidence_type and eligibility alone.
    const withoutIt = history([
      sourceSeries("snkrdunk", [
        segment([point("2026-09-01", 4300, FLOOR), point("2026-09-02", 4250, FLOOR)], FLOOR),
      ]),
    ]);
    const withIt = history([
      sourceSeries("snkrdunk", [
        segment(
          [
            point("2026-09-01", 4300, { ...FLOOR, ...({ price_type: "floor" } as object) }),
            point("2026-09-02", 4250, { ...FLOOR, ...({ price_type: "sell" } as object) }),
          ],
          FLOOR,
        ),
      ]),
    ]);

    const a = buildSeriesChartModel(withoutIt, allKeys(withoutIt));
    const b = buildSeriesChartModel(withIt, allKeys(withIt));

    expect(b.series[0].label).toBe(a.series[0].label);
    expect(b.series[0].strokes).toHaveLength(a.series[0].strokes.length);
    expect(b.series[0].strokes[0].points.map((p) => p.value_jpy)).toEqual([4300, 4250]);
  });

  it("says nothing about confidence, reliability or agreement", () => {
    const payload = history([
      marketIndex([
        segment([point("2026-09-01", 4100, { source_count: 3, coverage_status: "full" })], {
          index_version: 3,
        }),
      ]),
      sourceSeries("yuyutei", [segment([point("2026-09-01", 3980, RETAIL)], RETAIL)]),
    ]);
    const model = buildSeriesChartModel(payload, allKeys(payload));

    const words = JSON.stringify([
      model.series.map((entry) => entry.label),
      model.rows.map((row) => row.detail),
    ]);
    expect(words).not.toMatch(/confidence|reliab|agreement|accura|%/i);
  });

  it("computes no change between two points", () => {
    const payload = history([
      sourceSeries("yuyutei", [
        segment([point("2026-09-01", 1000, RETAIL), point("2026-09-02", 2000, RETAIL)], RETAIL),
      ]),
    ]);
    const model = buildSeriesChartModel(payload, allKeys(payload));

    // The model carries the observed values and nothing derived from them.
    const detail = model.rows.flatMap((row) => row.detail);
    expect(detail.map((d) => d.valueJpy)).toEqual([1000, 2000]);
    expect(Object.keys(detail[0]).sort()).toEqual([
      "constraint",
      "coverageStatus",
      "kind",
      "label",
      "plotted",
      "seriesKey",
      "valueJpy",
    ]);
  });
});

describe("J. labelling", () => {
  it("uses the frontend's existing instrument vocabulary", () => {
    expect(
      seriesDisplayLabel(
        sourceSeries("yuyutei", [segment([point("2026-09-01", 1, RETAIL)], RETAIL)]),
      ),
    ).toBe("Yuyu-Tei · Retail price");
    expect(
      seriesDisplayLabel(
        sourceSeries("snkrdunk", [segment([point("2026-09-01", 1, FLOOR)], FLOOR)]),
      ),
    ).toBe("SNKRDUNK · Current listing");
    expect(
      seriesDisplayLabel(
        sourceSeries("snkrdunk", [segment([point("2026-09-01", 1, MEDIAN)], MEDIAN)]),
      ),
    ).toBe("SNKRDUNK · Recent sales median");
  });

  it("never implies an asking price is a completed sale", () => {
    const retail = seriesDisplayLabel(
      sourceSeries("yuyutei", [segment([point("2026-09-01", 1, RETAIL)], RETAIL)]),
    );
    const floor = seriesDisplayLabel(
      sourceSeries("snkrdunk", [segment([point("2026-09-01", 1, FLOOR)], FLOOR)]),
    );

    expect(retail).not.toMatch(/sale|sold/i);
    expect(floor).not.toMatch(/sale|sold/i);
    // ...and a retail shop price is never described as a marketplace trade.
    expect(retail).not.toMatch(/market|listing/i);
  });

  it("leaves an auxiliary series out of the default selection", () => {
    const auxiliary = series({
      key: "source:yuyutei",
      kind: "source",
      source: "yuyutei",
      role: "auxiliary",
      segments: [segment([point("2026-09-01", 900, { reference_type: "dealer_buy" })])],
    });

    expect(isDefaultSelected(auxiliary)).toBe(false);
    expect(auxiliary.available).toBe(true);
  });
});

describe("K. the Market Index stays visible where it agrees with a source", () => {
  // The state that hid it: one eligible source, so the index holds exactly
  // that source's value and the two series sit on identical pixels.
  const coincident = history([
    marketIndex([segment([point("2026-09-01", 30), point("2026-09-02", 30)])]),
    sourceSeries("yuyutei", [
      segment([point("2026-09-01", 30, RETAIL), point("2026-09-02", 30, RETAIL)], RETAIL),
    ]),
  ]);

  it("paints the index last so a source cannot bury it", () => {
    const model = buildSeriesChartModel(coincident, allKeys(coincident));
    // The server's order - which the legend and tooltip use - still leads
    // with the index.
    expect(model.series[0].kind).toBe("market_index");
    // The PAINT order does not: last drawn is last on top.
    const painted = seriesPaintOrder(model.series);
    expect(painted[painted.length - 1].kind).toBe("market_index");
    expect(painted.map((entry) => entry.key)).toEqual(["source:yuyutei", "market_index"]);
  });

  it("keeps both series on the tooltip row when their values coincide", () => {
    const model = buildSeriesChartModel(coincident, allKeys(coincident));
    const detail = model.rows[0].detail;
    // Two readings of ¥30, still two - the chart may overlap them, but the
    // reader is never told there is only one.
    expect(detail).toHaveLength(2);
    expect(detail.every((entry) => entry.valueJpy === 30 && entry.plotted)).toBe(true);
    expect(detail.map((entry) => entry.label).sort()).toEqual([
      "Market Index",
      "Yuyu-Tei · Retail price",
    ]);
  });

  it("reorders nothing when there is no index selected", () => {
    const sourcesOnly = history([
      sourceSeries("yuyutei", [segment([point("2026-09-01", 30, RETAIL)], RETAIL)]),
      sourceSeries("snkrdunk", [segment([point("2026-09-01", 40, FLOOR)], FLOOR)]),
    ]);
    const model = buildSeriesChartModel(sourcesOnly, allKeys(sourcesOnly));
    expect(seriesPaintOrder(model.series).map((e) => e.key)).toEqual(
      model.series.map((e) => e.key),
    );
  });
});
