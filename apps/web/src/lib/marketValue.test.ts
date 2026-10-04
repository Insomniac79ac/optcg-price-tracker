import { beforeEach, expect, it, vi } from "vitest";
import fixtures from "./__fixtures__/marketValue.json";
const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("./api", () => ({ apiGet }));
import { fetchMarketValue, fetchMarketValueReleases, fetchMarketValueMovers, fetchMarketValueMostValuable, marketPercentagePoints, marketSignedJpy, marketChartPoints, marketDate, marketJpy, marketPercent, marketScopeUrl, movementUnavailable, parseMarketRelease, type MarketValue } from "./marketValue";
beforeEach(() => apiGet.mockReset().mockResolvedValue({}));

it("has dedicated Market Value requests with exact ID and window contracts", async () => {
  await fetchMarketValue(null, "7d");
  await fetchMarketValue(186, "30d");
  await fetchMarketValue(181, "all");
  await fetchMarketValueReleases();
  expect(apiGet.mock.calls).toEqual([
    ["/analytics/market-value", { params: { release_product_id: null, window: "7d" } }],
    ["/analytics/market-value", { params: { release_product_id: 186, window: "30d" } }],
    ["/analytics/market-value", { params: { release_product_id: 181, window: "all" } }],
    ["/analytics/market-value/releases"],
  ]);
});
it("uses server performance without deriving or rebasing it from values", () => {
  const points = [{ ...fixtures.overall.series[0], performance_pct: "12.3456", tracked_value_jpy: 1 }, { ...fixtures.overall.series[1], performance_pct: "-9.8765", tracked_value_jpy: 1000000 }];
  expect(marketChartPoints(points, "performance").map((r) => r.value)).toEqual([12.3456, -9.8765]);
  expect(marketChartPoints(points, "value").map((r) => r.value)).toEqual([1, 1000000]);
});
it("keeps explicit nulls and inserts a non-valued break for missing UTC days", () => {
  const rows = marketChartPoints([
    { ...fixtures.overall.series[0], date: "2026-09-20", performance_pct: "0" },
    { ...fixtures.overall.series[1], date: "2026-09-21", performance_pct: null },
    { ...fixtures.overall.series[2], date: "2026-09-24", performance_pct: "2" },
  ], "performance");
  expect(rows.map((r) => r.value)).toEqual([0, null, null, null, 2]);
  expect(rows[2].priced).toBeNull();
  expect(rows[2].date).toBe("2026-09-22");
  expect(rows[3].date).toBe("2026-09-23");
});
it("never forward fills a missing tracked JPY value", () => {
  expect(marketChartPoints([{ ...fixtures.overall.series[0], tracked_value_jpy: null }], "value")[0].value).toBeNull();
});
it("formats UTC archive dates, JPY and percentages without inventing missing zeroes", () => {
  expect(marketDate("2026-09-26", true)).toBe("Sep 26, 2026");
  expect(marketJpy(262279)).toBe("¥262,279");
  expect(marketJpy(null)).toBe("Not yet priced");
  expect(marketPercent("-3.943982")).toBe("−3.94%");
  expect(marketPercent("0")).toBe("0.00%");
  expect(marketPercent(null)).toBe("Unavailable");
  expect(marketPercent("-0.000001")).toBe("0.00%");
});
it("uses only release IDs in scope URLs", () => {
  expect(parseMarketRelease(null)).toBeNull();
  expect(parseMarketRelease("186")).toBe(186);
  expect(parseMarketRelease("OP-05")).toBe("invalid");
  expect(marketScopeUrl(186)).toBe("/analytics?release_product_id=186");
  expect(marketScopeUrl(null)).toBe("/analytics");
});
it("explains coverage and broken ALL histories without exposing internal reasons", () => {
  expect(movementUnavailable(fixtures.sparse as MarketValue).title).toBe("Price coverage in progress");
  const all = { ...fixtures.all, movement: { ...fixtures.all.movement, reason: "segment_break", available: false } } as MarketValue;
  expect(movementUnavailable(all).detail).toContain("the full archive");
  expect(movementUnavailable(all).detail).not.toContain("segment_break");
});

it.each(["gainers", "losers", "impact"] as const)("requests the server's %s cohort for Overall and release", async (order) => {
  await fetchMarketValueMovers(null, order);
  await fetchMarketValueMovers(186, order);
  expect(apiGet.mock.calls).toEqual([
    ["/analytics/market-value/movers", { params: { release_product_id: null, order, limit: 5 } }],
    ["/analytics/market-value/movers", { params: { release_product_id: 186, order, limit: 5 } }],
  ]);
});
it("requests exactly six most valuable prints with only catalogue scope", async () => {
  await fetchMarketValueMostValuable(null);
  await fetchMarketValueMostValuable(186);
  expect(apiGet.mock.calls).toEqual([
    ["/analytics/market-value/most-valuable", { params: { release_product_id: null, limit: 6 } }],
    ["/analytics/market-value/most-valuable", { params: { release_product_id: 186, limit: 6 } }],
  ]);
});
it("formats signed JPY and Decimal contribution without computing attribution", () => {
  expect(marketSignedJpy(-3200)).toBe("−¥3,200");
  expect(marketSignedJpy(460)).toBe("+¥460");
  expect(marketSignedJpy(0)).toBe("¥0");
  expect(marketPercentagePoints("-1.2100001")).toBe("−1.21 percentage points");
});

it.each([1, 2])("shows every missing calendar day as a null marker (%i days)", (missing) => {
  const original = [
    { ...fixtures.overall.series[0], date: "2026-09-26", tracked_value_jpy: 100 },
    { ...fixtures.overall.series[1], date: `2026-09-${27 + missing}`, tracked_value_jpy: 200 },
  ];
  const rows = marketChartPoints(original, "value");
  expect(rows.map((r) => r.value)).toEqual([100, ...Array(missing).fill(null), 200]);
  expect(rows.slice(1, -1).every((r) => r.priced === null && r.physical === null)).toBe(true);
  expect(original).toHaveLength(2);
});
it("keeps continuous history continuous and preserves single/empty histories", () => {
  const points = fixtures.overall.series;
  expect(marketChartPoints(points, "value").map((r) => r.value)).toEqual(points.map((p) => p.tracked_value_jpy));
  expect(marketChartPoints(points.slice(0, 1), "value")).toHaveLength(1);
  expect(marketChartPoints([], "value")).toEqual([]);
});
