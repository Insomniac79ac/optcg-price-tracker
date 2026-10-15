import { describe, expect, it } from "vitest";

import {
  coverageLine,
  parseCollectionWindow,
  shortDate,
  signedPct,
  signedYen,
  tileChange,
  unavailableReason,
  type CollectionEntry,
  type CollectionValue,
} from "./collection";

const entry = (over: Partial<CollectionEntry> = {}): CollectionEntry => ({
  id: 1,
  card_print_id: 101,
  resolution: "exact",
  quantity: 1,
  paid_jpy_per_card: null,
  acquired_on: null,
  note: null,
  legacy_card_id: null,
  print: null,
  value_status: "priced",
  value_per_card_jpy: 1000,
  value_jpy: 1000,
  ...over,
});

const value = (over: Partial<CollectionValue["movers"]> = {}, cards: CollectionValue["cards"] = []): CollectionValue =>
  ({
    movers: { available: true, reason: null, from_date: "2026-10-07", to_date: "2026-10-14", missing_dates: [], comparable_cards: 1, change_jpy: 10, change_pct: "1.00", up: [], down: [], ...over },
    cards,
  }) as unknown as CollectionValue;

describe("collection helpers", () => {
  it("reads the window from the query, defaulting to 7D", () => {
    expect(parseCollectionWindow(undefined)).toBe("7d");
    expect(parseCollectionWindow("30d")).toBe("30d");
    expect(parseCollectionWindow(["all", "7d"])).toBe("all");
    expect(parseCollectionWindow("90d")).toBe("7d");
  });

  it("formats the API's percentage with a sign and never invents one", () => {
    expect(signedPct("2.40")).toBe("+2.4%");
    expect(signedPct("-18.29")).toBe("−18.3%");
    expect(signedPct("0.04")).toBe("+0.04%");
    expect(signedPct("0.00")).toBe("0.0%");
    expect(signedPct(null)).toBeNull();
    expect(signedPct("")).toBeNull();
    expect(signedPct("abc")).toBeNull();
    expect(signedYen(-750)).toMatch(/^−/);
  });

  it("explains an unavailable window in words, never as 0%", () => {
    expect(unavailableReason({ reason: "not_enough_price_history" })).toBe("Not enough price history yet");
    expect(unavailableReason({ reason: "prices_missing", missing_dates: ["2026-09-27"] })).toBe("Prices missing on 27 Sept");
    expect(unavailableReason({ reason: "history_missing", missing_dates: ["2026-09-27", "2026-09-28"] })).toBe("Prices missing on 2 days");
    expect(unavailableReason({ reason: "something_new" })).toBe("Not available for this window");
    expect(unavailableReason(null)).toBe("Not available right now");
    for (const reason of ["not_enough_history", "no_prices_yet", "insufficient_comparable_value_coverage", null]) {
      expect(unavailableReason({ reason })).not.toMatch(/0%/);
    }
  });

  it("states coverage with the API's counts", () => {
    expect(coverageLine({ value_jpy: 1, priced_cards: 41, total_cards: 48, priced_entries: 1, total_entries: 1, unresolved_entries: 0, coverage_pct: "85.42" })).toBe(
      "Priced: 41 of 48 cards (85%)",
    );
    expect(coverageLine({ value_jpy: null, priced_cards: 0, total_cards: 1, priced_entries: 0, total_entries: 1, unresolved_entries: 1, coverage_pct: "0.00" })).toBe(
      "Priced: 0 of 1 card (0%)",
    );
  });

  it("reads dates as calendar days in UTC", () => {
    expect(shortDate("2026-10-14")).toBe("14 Oct");
    expect(shortDate(null)).toBeNull();
    expect(shortDate("nope")).toBeNull();
  });

  describe("per-card change", () => {
    it("uses the API's figure for a comparable version", () => {
      const v = value({}, [{ card_print_id: 101, units: 1, prior_value_per_card_jpy: 900, current_value_per_card_jpy: 1000, delta_jpy: 100, change_pct: "11.11", contribution_pct_points: "1" }]);
      expect(tileChange(v, entry())).toEqual({ kind: "change", pct: "+11.1%", direction: "up" });
    });

    it("says why when the version was not comparable", () => {
      expect(tileChange(value({}, []), entry())).toEqual({ kind: "none", reason: "Not priced at both ends of this window" });
    });

    it("never shows a change for an unavailable window", () => {
      const v = value({ available: false, reason: "not_enough_price_history", change_pct: null }, [
        { card_print_id: 101, units: 1, prior_value_per_card_jpy: 900, current_value_per_card_jpy: 1000, delta_jpy: 100, change_pct: "11.11", contribution_pct_points: "1" },
      ]);
      expect(tileChange(v, entry())).toEqual({ kind: "none", reason: "Not enough price history yet" });
    });

    it("never shows a change for an unpriced card, or when the value read failed", () => {
      expect(tileChange(value(), entry({ value_status: "no_price", value_jpy: null, value_per_card_jpy: null }))).toEqual({ kind: "none", reason: "No price yet" });
      expect(tileChange(null, entry())).toEqual({ kind: "none", reason: "Not available right now" });
    });

    it("works with an older API that has no per-card list", () => {
      const v = value();
      delete v.cards;
      expect(tileChange(v, entry()).kind).toBe("none");
    });
  });
});
