import { expect, it } from "vitest";
import fixtures from "./__fixtures__/marketValueReleases.json";
import type { MarketValue } from "./marketValue";
import { marketComparisonRows, releaseMovementReason } from "./marketValueComparison";
const all = Object.values(fixtures.series) as MarketValue[];

it("keeps server percentages on actual dates without calculating returns or rebasing", () => {
  const data = structuredClone(all.slice(0, 2));
  data[0].series[0].performance_pct = "12.345678";
  data[0].series[1].tracked_value_jpy = 999999999;
  const rows = marketComparisonRows(data)!;
  expect(rows).toHaveLength(8);
  expect(rows[0].date).toBe("2026-09-19");
  expect(rows[0].values[data[0].release_product_id!]).toBe(12.345678);
  expect(rows[1].values[data[0].release_product_id!]).toBe(Number(data[0].series[1].performance_pct));
  expect(rows.at(-1)!.values[data[1].release_product_id!]).toBe(Number(data[1].series.at(-1)!.performance_pct));
});
it("has no chart before selection", () => expect(marketComparisonRows([])).toBeNull());
it.each(["different dates", "missing day", "null performance", "unavailable", "wrong window", "invalid date", "different version", "wrong as_of"])("refuses %s instead of aligning or interpolating it", (edge) => {
  const data = structuredClone(all.slice(0, 2));
  if (edge === "different dates") data[1].series[7].date = "2026-09-27";
  if (edge === "missing day") data[1].series.splice(3, 1);
  if (edge === "null performance") data[1].series[3].performance_pct = null;
  if (edge === "unavailable") data[1].movement.available = false;
  if (edge === "wrong window") data[1].movement.window = "all";
  if (edge === "invalid date") data[1].series[2].date = "2026-09-99";
  if (edge === "different version") data[1].methodology_version = 2;
  if (edge === "wrong as_of") data[1].as_of = "2026-09-27";
  expect(marketComparisonRows(data)).toBeNull();
});
it.each([
  ["insufficient_comparable_prints", "Coverage in progress"],
  ["insufficient_physical_coverage", "Coverage in progress"],
  ["insufficient_window_continuity", "Not enough history"],
  ["segment_break", "Movement unavailable"],
  ["unknown_reason", "Movement unavailable"],
])("maps %s to collector copy", (reason, copy) => expect(releaseMovementReason(reason)).toBe(copy));
