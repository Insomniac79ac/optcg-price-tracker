import { describe, expect, it } from "vitest";

import { checkedAgo, targetDistance, watchChange, type WatchEntry } from "./watchlist";

const entry = (over: Partial<WatchEntry> = {}): WatchEntry => ({
  id: 1,
  card_print_id: 105,
  resolution: "exact",
  target_jpy: null,
  note: null,
  legacy_card_id: null,
  created_at: "2026-08-15T10:00:00Z",
  updated_at: "2026-08-15T10:00:00Z",
  print: null,
  value_status: "priced",
  value_jpy: 1000,
  target_gap_jpy: null,
  checked_at: null,
  change_7d_pct: null,
  change_7d_reason: null,
  ...over,
});

describe("watchlist helpers", () => {
  it("words the API's gap to the target", () => {
    expect(targetDistance({ target_jpy: 30000, target_gap_jpy: 1200 })).toBe("￥1,200 above your target");
    expect(targetDistance({ target_jpy: 30000, target_gap_jpy: -300 })).toBe("￥300 below your target");
    expect(targetDistance({ target_jpy: 30000, target_gap_jpy: 0 })).toBe("At your target");
    expect(targetDistance({ target_jpy: null, target_gap_jpy: null })).toBeNull();
    expect(targetDistance({ target_jpy: 30000, target_gap_jpy: null })).toBeNull();
  });

  it("says how long ago a source was checked, and unknown when it is not known", () => {
    const now = new Date("2026-10-15T12:00:00Z");
    expect(checkedAgo("2026-10-15T09:00:00Z", now)).toBe("Checked 3 h ago");
    expect(checkedAgo("2026-10-15T11:59:30Z", now)).toBe("Checked just now");
    expect(checkedAgo("2026-10-15T11:20:00Z", now)).toBe("Checked 40 min ago");
    expect(checkedAgo("2026-10-12T12:00:00Z", now)).toBe("Checked 3 days ago");
    expect(checkedAgo(null, now)).toBe("Check time unknown");
    expect(checkedAgo("nope", now)).toBe("Check time unknown");
  });

  it("uses the API's 7D change and never shows a missing one as 0%", () => {
    expect(watchChange(entry({ change_7d_pct: "4.20" }), {})).toEqual({ kind: "change", pct: "+4.2%", direction: "up" });
    expect(watchChange(entry({ change_7d_pct: "0.00" }), {})).toEqual({ kind: "change", pct: "0.0%", direction: "flat" });
    for (const reason of ["entrant", "contributor_set_changed", "index_version_changed", "not_enough_price_history", "no_prices_yet", "something_new"]) {
      const change = watchChange(entry({ change_7d_reason: reason }), {});
      expect(change.kind).toBe("none");
      if (change.kind === "none") expect(change.reason).not.toMatch(/0%/);
    }
    expect(watchChange(entry({ change_7d_reason: "entrant" }), {})).toEqual({ kind: "none", reason: "Not priced 7 days ago" });
    expect(watchChange(entry({ change_7d_reason: "prices_missing" }), { change_7d_missing_dates: ["2026-10-09"] })).toEqual({
      kind: "none",
      reason: "Prices missing on 9 Oct",
    });
  });

  it("works with an older API that has no 7D fields", () => {
    const old = entry();
    delete old.change_7d_pct;
    delete old.change_7d_reason;
    expect(watchChange(old, {})).toEqual({ kind: "none", reason: "Not available right now" });
  });
});
