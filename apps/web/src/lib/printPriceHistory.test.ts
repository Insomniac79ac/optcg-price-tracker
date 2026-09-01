/** What the "Price history" section is allowed to say about a print.
 *
 * These are behaviour tests for the decisions in printPriceHistory.ts, not
 * snapshot tests of a chart: the invariants that matter here are "a
 * constrained value never becomes a price line", "a single observation never
 * becomes a trend", "a null change never becomes 0%" and "a sibling print's
 * observation never reaches this page". Each is asserted on the view model,
 * which is where the decision is actually made.
 */

import { describe, expect, it } from "vitest";

import {
  buildChartRows,
  buildPriceHistoryView,
  segmentDataKey,
  seriesKey,
} from "./printPriceHistory";
import type { PrintPriceHistory, PrintPriceObservation, PrintPriceSeriesTrend } from "./prints";

let nextId = 1;

function observation(
  overrides: Partial<PrintPriceObservation> & Pick<PrintPriceObservation, "observed_at">,
): PrintPriceObservation {
  return {
    id: nextId++,
    card_print_id: 11,
    source_id: 1,
    source: "yuyutei",
    price_type: "sell",
    price_jpy: 1000,
    condition_label: null,
    listing_count: null,
    raw_snapshot_id: 1,
    constraint: null,
    eligible: true,
    ineligible_reason: null,
    ...overrides,
  };
}

function trend(overrides: Partial<PrintPriceSeriesTrend> = {}): PrintPriceSeriesTrend {
  return {
    source: "yuyutei",
    price_type: "sell",
    latest_price_jpy: 1000,
    latest_observed_at: "2026-08-31T00:00:00Z",
    sufficient_history: true,
    change_24h_pct: null,
    change_7d_pct: null,
    change_30d_pct: null,
    ...overrides,
  };
}

function history(
  observations: PrintPriceObservation[],
  series: PrintPriceSeriesTrend[] = [],
  cardPrintId = 11,
): PrintPriceHistory {
  return { card_print_id: cardPrintId, observations, series };
}

/** The SNKRDUNK platform-minimum reading, exactly as the deployed API sends
 * it. The ¥1,000 here is data, never a rule: nothing in the module under test
 * looks at the number, and these tests would pass identically if the platform
 * minimum changed tomorrow. */
function constrainedSnkrdunk(observedAt: string, priceJpy = 1000): PrintPriceObservation {
  return observation({
    observed_at: observedAt,
    source: "snkrdunk",
    source_id: 2,
    price_type: "floor",
    price_jpy: priceJpy,
    constraint: "platform_floor",
    eligible: false,
    ineligible_reason: "platform_floor",
  });
}

describe("A. rich history", () => {
  it("plots both sources when each has eligible observations on 2+ dates", () => {
    const view = buildPriceHistoryView(
      history([
        observation({ observed_at: "2026-08-01T00:00:00Z", price_jpy: 7980 }),
        observation({ observed_at: "2026-08-02T00:00:00Z", price_jpy: 9980 }),
        observation({
          observed_at: "2026-08-01T00:00:00Z",
          source: "snkrdunk",
          source_id: 2,
          price_type: "floor",
          price_jpy: 6888,
        }),
        observation({
          observed_at: "2026-08-02T00:00:00Z",
          source: "snkrdunk",
          source_id: 2,
          price_type: "floor",
          price_jpy: 5444,
        }),
      ]),
      11,
    );

    expect(view.series).toHaveLength(2);
    expect(view.series.every((entry) => entry.mode === "plotted")).toBe(true);
    expect(view.hasChart).toBe(true);

    const yuyutei = view.series.find((entry) => entry.source === "yuyutei")!;
    expect(yuyutei.points.map((p) => p.priceJpy)).toEqual([7980, 9980]);
    expect(yuyutei.segments).toHaveLength(1);
    expect(yuyutei.latest?.priceJpy).toBe(9980);
  });
});

describe("B. thin history", () => {
  it("does not fabricate a trend line from a single eligible observation", () => {
    const view = buildPriceHistoryView(
      history(
        [observation({ observed_at: "2026-08-30T00:00:00Z", price_jpy: 14000 })],
        [trend({ sufficient_history: false })],
      ),
      11,
    );

    const [series] = view.series;
    expect(series.mode).toBe("compact");
    expect(series.distinctDateCount).toBe(1);
    expect(series.segments).toEqual([]);
    expect(view.hasChart).toBe(false);
    expect(buildChartRows(view.series)).toEqual([]);
  });

  it("is still compact when several observations land on one calendar date", () => {
    const view = buildPriceHistoryView(
      history([
        observation({ observed_at: "2026-08-30T01:00:00Z", price_jpy: 3300 }),
        observation({ observed_at: "2026-08-30T09:00:00Z", price_jpy: 3300 }),
        observation({ observed_at: "2026-08-30T19:00:00Z", price_jpy: 3300 }),
      ]),
      11,
    );

    expect(view.series[0].mode).toBe("compact");
    expect(view.series[0].points).toHaveLength(3);
    expect(view.hasChart).toBe(false);
  });
});

describe("C. constrained SNKRDUNK", () => {
  it("never renders platform-floor observations as a market-price line", () => {
    const view = buildPriceHistoryView(
      history(
        [
          constrainedSnkrdunk("2026-08-28T00:00:00Z"),
          constrainedSnkrdunk("2026-08-29T00:00:00Z"),
          constrainedSnkrdunk("2026-08-30T00:00:00Z"),
        ],
        [
          trend({
            source: "snkrdunk",
            price_type: "floor",
            latest_price_jpy: 1000,
            change_24h_pct: 0,
            change_7d_pct: 0,
          }),
        ],
      ),
      11,
    );

    const [series] = view.series;
    expect(series.mode).toBe("constrained");
    expect(series.points).toEqual([]);
    expect(series.segments).toEqual([]);
    expect(series.latest).toBeNull();
    expect(view.hasChart).toBe(false);
    // No plotted segment means no chart row can carry the ¥1,000 anywhere.
    expect(buildChartRows(view.series)).toEqual([]);

    // The raw values are preserved and counted, never hidden.
    expect(series.constrainedCount).toBe(3);
    expect(series.constrainedLatestJpy).toBe(1000);
    expect(series.constraint).toBe("platform_floor");

    // A backend change computed across constrained readings would describe
    // movement in something that is not a market price.
    expect(series.changes).toEqual([]);
  });
});

describe("D. mixed future series", () => {
  it("does not connect eligible points across a constrained observation", () => {
    const view = buildPriceHistoryView(
      history([
        observation({
          observed_at: "2026-08-01T00:00:00Z",
          source: "snkrdunk",
          source_id: 2,
          price_type: "floor",
          price_jpy: 4000,
        }),
        constrainedSnkrdunk("2026-08-02T00:00:00Z"),
        observation({
          observed_at: "2026-08-03T00:00:00Z",
          source: "snkrdunk",
          source_id: 2,
          price_type: "floor",
          price_jpy: 4200,
        }),
      ]),
      11,
    );

    const [series] = view.series;
    expect(series.mode).toBe("plotted");
    // Two runs, not one: the line is broken at the constrained reading.
    expect(series.segments).toHaveLength(2);
    expect(series.segments[0].points.map((p) => p.priceJpy)).toEqual([4000]);
    expect(series.segments[1].points.map((p) => p.priceJpy)).toEqual([4200]);

    // Each run is a separate chart key, so there is no path between them for
    // the renderer to stroke, and the constrained timestamp holds no value.
    const key = seriesKey("snkrdunk", "floor");
    const rows = buildChartRows(view.series);
    const constrainedRow = rows.find((row) => row.t === Date.parse("2026-08-02T00:00:00Z"));
    expect(constrainedRow).toBeUndefined();
    expect(rows[0][segmentDataKey(key, 0)]).toBe(4000);
    expect(rows[0][segmentDataKey(key, 1)]).toBeUndefined();
    expect(rows[1][segmentDataKey(key, 1)]).toBe(4200);
    expect(rows[1][segmentDataKey(key, 0)]).toBeUndefined();
  });
});

describe("E. null change fields", () => {
  it("omits null windows rather than reporting them as 0%", () => {
    const view = buildPriceHistoryView(
      history(
        [
          observation({ observed_at: "2026-08-01T00:00:00Z", price_jpy: 1000 }),
          observation({ observed_at: "2026-08-02T00:00:00Z", price_jpy: 1200 }),
        ],
        [trend({ change_24h_pct: -20.96, change_7d_pct: null, change_30d_pct: null })],
      ),
      11,
    );

    expect(view.series[0].changes).toEqual([{ label: "24h", pct: -20.96 }]);
  });

  it("keeps a genuine zero, which is a measurement rather than a gap", () => {
    const view = buildPriceHistoryView(
      history(
        [
          observation({ observed_at: "2026-08-01T00:00:00Z" }),
          observation({ observed_at: "2026-08-02T00:00:00Z" }),
        ],
        [trend({ change_24h_pct: 0, change_7d_pct: 0, change_30d_pct: null })],
      ),
      11,
    );

    expect(view.series[0].changes).toEqual([
      { label: "24h", pct: 0 },
      { label: "7d", pct: 0 },
    ]);
  });

  it("reports no changes at all when every window is null", () => {
    const view = buildPriceHistoryView(
      history(
        [
          observation({ observed_at: "2026-08-01T00:00:00Z" }),
          observation({ observed_at: "2026-08-02T00:00:00Z" }),
        ],
        [trend()],
      ),
      11,
    );

    expect(view.series[0].changes).toEqual([]);
  });
});

describe("F. source labels", () => {
  it("keeps Yuyu-Tei sell and SNKRDUNK listing floor semantically distinct", () => {
    const view = buildPriceHistoryView(
      history([
        observation({ observed_at: "2026-08-01T00:00:00Z" }),
        observation({
          observed_at: "2026-08-01T00:00:00Z",
          source: "snkrdunk",
          source_id: 2,
          price_type: "floor",
        }),
      ]),
      11,
    );

    const labels = view.series.map((entry) => entry.label);
    expect(labels).toContain("Yuyu-Tei sell");
    expect(labels).toContain("SNKRDUNK listing floor");
    expect(new Set(view.series.map((entry) => entry.key)).size).toBe(2);
  });

  it("keeps two price types from one source apart", () => {
    const view = buildPriceHistoryView(
      history([
        observation({ observed_at: "2026-08-01T00:00:00Z", price_type: "sell" }),
        observation({ observed_at: "2026-08-01T00:00:00Z", price_type: "dealer_buy" }),
      ]),
      11,
    );

    expect(view.series.map((entry) => entry.label).sort()).toEqual([
      "Yuyu-Tei dealer buy",
      "Yuyu-Tei sell",
    ]);
  });
});

describe("G. exact-print isolation", () => {
  it("drops observations belonging to a sibling print", () => {
    const view = buildPriceHistoryView(
      history([
        observation({ observed_at: "2026-08-01T00:00:00Z", card_print_id: 11, price_jpy: 7980 }),
        observation({ observed_at: "2026-08-02T00:00:00Z", card_print_id: 11, price_jpy: 8980 }),
        // The same card's other printing - a different collectible, and never
        // this page's price.
        observation({ observed_at: "2026-08-03T00:00:00Z", card_print_id: 12, price_jpy: 99000 }),
      ]),
      11,
    );

    const prices = view.series.flatMap((entry) => entry.points.map((p) => p.priceJpy));
    expect(prices).toEqual([7980, 8980]);
    expect(prices).not.toContain(99000);
  });

  it("renders nothing when every observation belongs to another print", () => {
    const view = buildPriceHistoryView(
      history([observation({ observed_at: "2026-08-01T00:00:00Z", card_print_id: 12 })]),
      11,
    );

    expect(view.series).toEqual([]);
    expect(view.hasChart).toBe(false);
  });
});

describe("backward compatibility", () => {
  it("treats an observation with no semantics fields as eligible", () => {
    // An API older than the source-semantics release omits all three fields.
    const legacy: PrintPriceObservation = {
      id: 1,
      card_print_id: 11,
      source_id: 1,
      source: "yuyutei",
      observed_at: "2026-08-01T00:00:00Z",
      price_type: "sell",
      price_jpy: 1980,
      condition_label: null,
      listing_count: null,
      raw_snapshot_id: 1,
    };

    const view = buildPriceHistoryView(
      history([legacy, { ...legacy, id: 2, observed_at: "2026-08-02T00:00:00Z" }]),
      11,
    );

    expect(view.series[0].mode).toBe("plotted");
    expect(view.series[0].constrainedCount).toBe(0);
  });
});
