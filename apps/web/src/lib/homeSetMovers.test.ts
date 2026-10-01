import { describe, expect, it } from "vitest";
import { homeSetMovers } from "./homeSetMovers";
import fixture from "./__fixtures__/marketValue.json";
const base = fixture.releases.items[2];
describe("homepage set movers", () => {
  it("ranks comparable 7D magnitude across gains and falls, not recency, price or count", () => {
    const items = [
      { ...base, release_product_id: 1, seven_day: { available: true, reason: "publishable", pct: "2" } },
      { ...base, release_product_id: 2, seven_day: { available: true, reason: "publishable", pct: "-8" } },
      { ...base, release_product_id: 3, seven_day: { available: true, reason: "publishable", pct: "5" } },
    ];
    expect(homeSetMovers(items).map((s) => s.release_product_id)).toEqual([2, 3, 1]);
    expect(items.map((s) => s.release_product_id)).toEqual([1, 2, 3]);
  });
  it("excludes null, withheld, non-finite and older publications without padding", () => {
    const items = [base, ...[null, "NaN", "Infinity"].map((pct) => ({ ...base, seven_day: { ...base.seven_day, pct } })),
      { ...base, as_of: "2026-09-25" }, { ...base, seven_day: { ...base.seven_day, available: false, pct: "999" } },
      { ...base, seven_day: { ...base.seven_day, reason: "insufficient_window_continuity" } }];
    expect(homeSetMovers(items)).toEqual([base]);
  });
  it("retains an actually available zero and returns no invented rows", () => {
    expect(homeSetMovers([])).toEqual([]);
    const zero = { ...base, seven_day: { ...base.seven_day, pct: "0" } };
    expect(homeSetMovers([zero])).toEqual([zero]);
  });
});
