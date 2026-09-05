/** What the "Price history" section is allowed to say about a print.
 *
 * These are behaviour tests for the decisions in printPriceHistory.ts, not
 * snapshot tests of a chart: the invariants that matter here are "a
 * constrained value is never treated as a price", "a single observation never
 * becomes a trend", "a null change never becomes 0%" and "a sibling print's
 * observation never reaches this page". Each is asserted on the view model,
 * which is where the decision is actually made.
 *
 * THE LINE-GEOMETRY INVARIANTS MOVED. Which points a stroke may join, and
 * where it must break, is now decided in printSeries.ts against the server's
 * own segments - see printSeries.test.ts, which asserts the same "never draw
 * through a constrained observation" rule this file used to.
 */

import { describe, expect, it } from "vitest";

import { buildPriceHistoryView, seriesLabel } from "./printPriceHistory";
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
    // The instrument the SERVER resolved for this row. Deliberately supplied
    // independently of `price_type`: every fixture that changes the stored
    // type must state the reference_type too, because nothing in the module
    // under test may derive one from the other.
    reference_type: "retail_sell",
    evidence_type: "listing",
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
    reference_type: "listing_floor",
    evidence_type: "listing",
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
          reference_type: "listing_floor",
          price_jpy: 6888,
        }),
        observation({
          observed_at: "2026-08-02T00:00:00Z",
          source: "snkrdunk",
          source_id: 2,
          price_type: "floor",
          reference_type: "listing_floor",
          price_jpy: 5444,
        }),
      ]),
      11,
    );

    expect(view.series).toHaveLength(2);
    expect(view.series.every((entry) => entry.mode === "plotted")).toBe(true);

    const yuyutei = view.series.find((entry) => entry.source === "yuyutei")!;
    expect(yuyutei.points.map((p) => p.priceJpy)).toEqual([7980, 9980]);
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
    expect(series.changes).toEqual([]);
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
    expect(series.latest).toBeNull();

    // The raw values are preserved and counted, never hidden.
    expect(series.constrainedCount).toBe(3);
    expect(series.constrainedLatestJpy).toBe(1000);
    expect(series.constraint).toBe("platform_floor");

    // A backend change computed across constrained readings would describe
    // movement in something that is not a market price.
    expect(series.changes).toEqual([]);
  });
});

describe("D. a series interrupted by a constrained reading", () => {
  it("counts the constrained reading without letting it become a price", () => {
    // Where the LINE breaks is printSeries.ts's decision now (see
    // printSeries.test.ts, "never draws through a constrained observation").
    // What this module still owns is the row beneath it: the eligible prices
    // are the series' prices, and the disqualified reading is counted and
    // named rather than averaged into them.
    const view = buildPriceHistoryView(
      history([
        observation({
          observed_at: "2026-08-01T00:00:00Z",
          source: "snkrdunk",
          source_id: 2,
          price_type: "floor",
          reference_type: "listing_floor",
          price_jpy: 4000,
        }),
        constrainedSnkrdunk("2026-08-02T00:00:00Z"),
        observation({
          observed_at: "2026-08-03T00:00:00Z",
          source: "snkrdunk",
          source_id: 2,
          price_type: "floor",
          reference_type: "listing_floor",
          price_jpy: 4200,
        }),
      ]),
      11,
    );

    const [series] = view.series;
    expect(series.mode).toBe("plotted");
    expect(series.points.map((p) => p.priceJpy)).toEqual([4000, 4200]);
    expect(series.latest?.priceJpy).toBe(4200);
    expect(series.constrainedCount).toBe(1);
    expect(series.constraint).toBe("platform_floor");
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
  it("names each source series in the ONE collector vocabulary", () => {
    const view = buildPriceHistoryView(
      history([
        observation({ observed_at: "2026-08-01T00:00:00Z" }),
        observation({
          observed_at: "2026-08-01T00:00:00Z",
          source: "snkrdunk",
          source_id: 2,
          price_type: "floor",
          reference_type: "listing_floor",
        }),
      ]),
      11,
    );

    const labels = view.series.map((entry) => entry.label);
    // The SAME words and shape the chart's chips use - one vocabulary per
    // quantity, not one for the chip and another for the row beneath it.
    expect(labels).toContain("Yuyu-Tei · Retail price");
    expect(labels).toContain("SNKRDUNK · Current listing");
    // The stored names never reach the screen...
    expect(labels.join(" ")).not.toMatch(/listing floor|\bsell\b|\bfloor\b/i);
    // ...but they remain the row's identity, so two series stay distinct.
    expect(new Set(view.series.map((entry) => entry.key)).size).toBe(2);
    expect(view.series.map((entry) => entry.priceType).sort()).toEqual(["floor", "sell"]);
  });

  it("labels a series from the server's reference_type, never its stored type", () => {
    // The argument is the API-facing instrument. A stored price_type is not
    // accepted here and would not be understood if it were: `seriesLabel`
    // holds no table that turns "floor" into a listing floor.
    expect(seriesLabel("snkrdunk", "listing_floor")).toBe("SNKRDUNK · Current listing");
    expect(seriesLabel("yuyutei", "retail_sell")).toBe("Yuyu-Tei · Retail price");
    expect(seriesLabel("snkrdunk", "transaction_median")).toBe("SNKRDUNK · Recent sales median");
  });

  it("humanises an instrument this build has never heard of", () => {
    // Named, not guessed at, and never dropped.
    expect(seriesLabel("newshop", "auction_high")).toBe("newshop · Auction high");
  });

  it("names the platform alone when the server named no instrument", () => {
    // A future source Atlas has no instrument rule for yet. Its prices are
    // still real and still shown; what is NOT invented is a claim about what
    // they measure - and nothing here reaches for the stored token to fill
    // the gap.
    const view = buildPriceHistoryView(
      history([
        observation({
          observed_at: "2026-08-01T00:00:00Z",
          source: "cardrush",
          source_id: 7,
          price_type: "shop_asking",
          price_jpy: 880,
          reference_type: null,
          evidence_type: null,
        }),
        observation({
          observed_at: "2026-08-02T00:00:00Z",
          source: "cardrush",
          source_id: 7,
          price_type: "shop_asking",
          price_jpy: 910,
          reference_type: null,
          evidence_type: null,
        }),
      ]),
      11,
    );

    const [series] = view.series;
    expect(series.label).toBe("cardrush");
    expect(series.label).not.toMatch(/shop.asking/i);
    expect(series.referenceType).toBeNull();
    // Unnamed does not mean unusable: it segments, plots and reports normally.
    expect(series.mode).toBe("plotted");
    expect(series.points.map((point) => point.priceJpy)).toEqual([880, 910]);
    expect(series.key).toBe("cardrush:shop_asking");
  });

  it("labels a future server-defined instrument with no change to this module", () => {
    // The same unrecognised source, this time with an instrument the server
    // HAS named. Segmentation and mode are untouched; only the words change,
    // and they are the server's own token humanised.
    const view = buildPriceHistoryView(
      history([
        observation({
          observed_at: "2026-08-01T00:00:00Z",
          source: "cardmarket",
          source_id: 8,
          price_type: "trend_eur",
          price_jpy: 1200,
          reference_type: "market_trend",
          evidence_type: "listing",
        }),
      ]),
      11,
    );

    const [series] = view.series;
    expect(series.label).toBe("cardmarket · Market trend");
    expect(series.referenceType).toBe("market_trend");
    expect(series.evidenceType).toBe("listing");
  });

  it("keeps two instruments from one source apart", () => {
    const view = buildPriceHistoryView(
      history([
        observation({
          observed_at: "2026-08-01T00:00:00Z",
          price_type: "sell",
          reference_type: "retail_sell",
        }),
        observation({
          observed_at: "2026-08-01T00:00:00Z",
          price_type: "buy",
          reference_type: "dealer_buy",
        }),
      ]),
      11,
    );

    expect(view.series.map((entry) => entry.label).sort()).toEqual([
      "Yuyu-Tei · Dealer buy price",
      "Yuyu-Tei · Retail price",
    ]);
    // Grouped by the STORED type - two rows even though this module never
    // read what either stored token means.
    expect(view.series.map((entry) => entry.priceType).sort()).toEqual(["buy", "sell"]);
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

  it("names an observation with no instrument fields by its platform alone", () => {
    // An API older than the instrument release omits reference_type and
    // evidence_type. The stored "sell" is RIGHT THERE and is still not
    // decoded: the row is "Yuyu-Tei", which is everything this payload
    // actually establishes.
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

    const view = buildPriceHistoryView(history([legacy]), 11);

    expect(view.series[0].label).toBe("Yuyu-Tei");
    expect(view.series[0].referenceType).toBeNull();
    expect(view.series[0].evidenceType).toBeNull();
    expect(view.series[0].priceType).toBe("sell");
  });
});
