/** Contract tests for `GET /prints/{id}/prices` as the frontend types it.
 *
 * These exist because the frontend's `PrintPriceSeriesTrend` had drifted away
 * from schemas.py `PrintPriceSeriesTrendOut` - it still described a
 * previous/change/observation_count shape the API has never sent. Nothing
 * rendered it, so nothing broke; the drift was only ever going to be caught
 * by pinning the contract here.
 *
 * The fixture below is a real-shaped response: the exact field set
 * services/api/app/api/prints.py::get_print_prices builds, with one
 * multi-observation series (real change_*_pct) and one single-observation
 * series (sufficient_history false, every change null). Type errors are as
 * much the point as the assertions - the `@ts-expect-error` blocks fail
 * `tsc --noEmit` if a removed field ever creeps back in.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchPrintPrices,
  type PrintPriceHistory,
  type PrintPriceObservation,
  type PrintPriceSeriesTrend,
} from "./prints";

/** Verbatim-shaped `GET /prints/3/prices` body. */
const RESPONSE: PrintPriceHistory = {
  card_print_id: 3,
  observations: [
    {
      id: 9012,
      card_print_id: 3,
      source_id: 1,
      source: "yuyutei",
      observed_at: "2026-08-11T19:21:25.989165Z",
      price_type: "retail_sell",
      price_jpy: 1980,
      condition_label: "A",
      listing_count: 4,
      raw_snapshot_id: 771,
    },
    {
      id: 8801,
      card_print_id: 3,
      source_id: 1,
      source: "yuyutei",
      observed_at: "2026-07-11T19:04:11.120000Z",
      price_type: "retail_sell",
      price_jpy: 1650,
      condition_label: null,
      listing_count: null,
      raw_snapshot_id: null,
    },
    {
      id: 9013,
      card_print_id: 3,
      source_id: 2,
      source: "snkrdunk",
      observed_at: "2026-08-11T18:20:37.385148Z",
      price_type: "listing_floor",
      price_jpy: 1500,
      condition_label: null,
      listing_count: 2,
      raw_snapshot_id: 772,
    },
  ],
  series: [
    {
      source: "snkrdunk",
      price_type: "listing_floor",
      latest_price_jpy: 1500,
      latest_observed_at: "2026-08-11T18:20:37.385148Z",
      sufficient_history: false,
      change_24h_pct: null,
      change_7d_pct: null,
      change_30d_pct: null,
    },
    {
      source: "yuyutei",
      price_type: "retail_sell",
      latest_price_jpy: 1980,
      latest_observed_at: "2026-08-11T19:21:25.989165Z",
      sufficient_history: true,
      change_24h_pct: null,
      change_7d_pct: 20.0,
      change_30d_pct: 20.0,
    },
  ],
};

function stubFetchOnce(body: unknown): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchPrintPrices", () => {
  it("requests the print-scoped prices endpoint", async () => {
    const fetchMock = stubFetchOnce(RESPONSE);
    await fetchPrintPrices(3);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/prints/3/prices");
  });

  it("flows a representative backend response through unchanged", async () => {
    stubFetchOnce(RESPONSE);
    const history = await fetchPrintPrices(3);
    expect(history).toEqual(RESPONSE);
    expect(history.card_print_id).toBe(3);
    expect(history.observations).toHaveLength(3);
    expect(history.series).toHaveLength(2);
  });

  it("accepts a string print id", async () => {
    const fetchMock = stubFetchOnce(RESPONSE);
    await fetchPrintPrices("3");
    expect(String(fetchMock.mock.calls[0][0])).toContain("/prints/3/prices");
  });
});

describe("PrintPriceSeriesTrend", () => {
  it("carries the latest observation's timestamp as an ISO-8601 string", async () => {
    stubFetchOnce(RESPONSE);
    const { series } = await fetchPrintPrices(3);
    const yuyutei = series.find((entry) => entry.source === "yuyutei")!;

    // The API sends a JSON string, not a Date - nothing in the transport
    // revives it, so consumers get exactly what FastAPI serialised.
    expect(typeof yuyutei.latest_observed_at).toBe("string");
    expect(yuyutei.latest_observed_at).toBe("2026-08-11T19:21:25.989165Z");
    // And it is the timestamp of the observation behind latest_price_jpy,
    // not merely some observation in the series.
    const latestObservation = RESPONSE.observations.find(
      (obs) => obs.id === 9012,
    )!;
    expect(yuyutei.latest_observed_at).toBe(latestObservation.observed_at);
    expect(yuyutei.latest_price_jpy).toBe(latestObservation.price_jpy);
    expect(Number.isNaN(Date.parse(yuyutei.latest_observed_at))).toBe(false);
  });

  it("exposes sufficient_history per series", async () => {
    stubFetchOnce(RESPONSE);
    const { series } = await fetchPrintPrices(3);
    const bySource = Object.fromEntries(series.map((entry) => [entry.source, entry]));
    expect(bySource.yuyutei.sufficient_history).toBe(true);
    expect(bySource.snkrdunk.sufficient_history).toBe(false);
  });

  it("supports null 24h/7d/30d changes without substituting a number", async () => {
    stubFetchOnce(RESPONSE);
    const { series } = await fetchPrintPrices(3);
    const snkrdunk = series.find((entry) => entry.source === "snkrdunk")!;

    // A single-observation series: no baseline exists, so no window has a
    // change. Null must survive as null - never coerced to 0.
    expect(snkrdunk.change_24h_pct).toBeNull();
    expect(snkrdunk.change_7d_pct).toBeNull();
    expect(snkrdunk.change_30d_pct).toBeNull();

    // A series can also have history but still lack a baseline inside one
    // window specifically - the 24h window here.
    const yuyutei = series.find((entry) => entry.source === "yuyutei")!;
    expect(yuyutei.sufficient_history).toBe(true);
    expect(yuyutei.change_24h_pct).toBeNull();
    expect(yuyutei.change_7d_pct).toBe(20.0);
  });

  it("types every change window as nullable and the latest price as non-null", () => {
    const nulled: PrintPriceSeriesTrend = {
      source: "yuyutei",
      price_type: "retail_sell",
      latest_price_jpy: 1980,
      latest_observed_at: "2026-08-11T19:21:25.989165Z",
      sufficient_history: false,
      change_24h_pct: null,
      change_7d_pct: null,
      change_30d_pct: null,
    };
    expect(nulled.change_30d_pct).toBeNull();

    // @ts-expect-error latest_price_jpy is required and never null - the
    // backend only emits a series it has a latest observation for.
    const missingLatest: PrintPriceSeriesTrend = { ...nulled, latest_price_jpy: null };
    expect(missingLatest.latest_price_jpy).toBeNull();

    // @ts-expect-error latest_observed_at is required for the same reason.
    const missingObservedAt: PrintPriceSeriesTrend = { ...nulled, latest_observed_at: null };
    expect(missingObservedAt.latest_observed_at).toBeNull();
  });

  it("no longer expects the obsolete previous/change/count fields", () => {
    const trend: PrintPriceSeriesTrend = {
      source: "yuyutei",
      price_type: "retail_sell",
      latest_price_jpy: 1980,
      latest_observed_at: "2026-08-11T19:21:25.989165Z",
      sufficient_history: true,
      change_24h_pct: 1.5,
      change_7d_pct: null,
      change_30d_pct: null,
    };

    // The API has never sent these. Each line fails `tsc --noEmit` if the
    // field is ever reintroduced without the backend growing it first.
    // @ts-expect-error previous_price_jpy is not part of PrintPriceSeriesTrendOut
    expect(trend.previous_price_jpy).toBeUndefined();
    // @ts-expect-error change_jpy is not part of PrintPriceSeriesTrendOut
    expect(trend.change_jpy).toBeUndefined();
    // @ts-expect-error change_pct is not part of PrintPriceSeriesTrendOut
    expect(trend.change_pct).toBeUndefined();
    // @ts-expect-error observation_count is not part of PrintPriceSeriesTrendOut
    expect(trend.observation_count).toBeUndefined();

    // And they are genuinely absent from a real response, not merely untyped.
    for (const entry of RESPONSE.series) {
      expect(Object.keys(entry).sort()).toEqual([
        "change_24h_pct",
        "change_30d_pct",
        "change_7d_pct",
        "latest_observed_at",
        "latest_price_jpy",
        "price_type",
        "source",
        "sufficient_history",
      ]);
    }
  });
});

describe("PrintPriceObservation and PrintPriceHistory (unchanged)", () => {
  it("keeps PrintPriceObservation's field set, nullability included", () => {
    const observation: PrintPriceObservation = {
      id: 9012,
      card_print_id: 3,
      source_id: 1,
      source: "yuyutei",
      observed_at: "2026-08-11T19:21:25.989165Z",
      price_type: "retail_sell",
      price_jpy: 1980,
      condition_label: null,
      listing_count: null,
      raw_snapshot_id: null,
    };
    expect(Object.keys(observation).sort()).toEqual([
      "card_print_id",
      "condition_label",
      "id",
      "listing_count",
      "observed_at",
      "price_jpy",
      "price_type",
      "raw_snapshot_id",
      "source",
      "source_id",
    ]);

    // Deliberately no stock field - see PrintPriceObservationOut's docstring:
    // the print-centric model does not depend on Yuyu-Tei stock.
    // @ts-expect-error the print-scoped observation has no stock field
    expect(observation.in_stock).toBeUndefined();
  });

  it("keeps PrintPriceHistory as card_print_id + observations + series", () => {
    expect(Object.keys(RESPONSE).sort()).toEqual([
      "card_print_id",
      "observations",
      "series",
    ]);
  });
});
