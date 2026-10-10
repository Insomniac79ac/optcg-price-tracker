import { describe, expect, it } from "vitest";

import { DASHBOARD_WIDGET_IDS } from "@/lib/api";
import { buildFullOrder, isShownWidget } from "@/lib/dashboardWidgets";

const ADMIN_ONLY = ["top_opportunities", "market_report", "recent_signal_events"];

describe("dashboard widgets withhold admin-only market data", () => {
  it("never shows the opportunity, market report or signal-event widgets", () => {
    for (const id of ADMIN_ONLY) expect(isShownWidget(id)).toBe(false);
    expect(isShownWidget("portfolio_summary")).toBe(true);
    expect(isShownWidget("not_a_widget")).toBe(false);
  });

  it("drops them from a saved layout and from the Customize order", () => {
    const order = buildFullOrder(["market_report", "wishlist_targets", "top_opportunities"]);

    expect(order[0]).toBe("wishlist_targets");
    expect(order.filter((id) => ADMIN_ONLY.includes(id))).toEqual([]);
    expect(order).toHaveLength(DASHBOARD_WIDGET_IDS.length - ADMIN_ONLY.length);
  });
});
