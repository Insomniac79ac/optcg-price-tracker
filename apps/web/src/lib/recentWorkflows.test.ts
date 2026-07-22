import { beforeEach, describe, expect, it } from "vitest";

import { clearRecentWorkflows, getRecentWorkflows, recordRecentWorkflow } from "./recentWorkflows";

describe("recentWorkflows", () => {
  beforeEach(() => {
    clearRecentWorkflows();
  });

  it("returns an empty list initially", () => {
    expect(getRecentWorkflows()).toEqual([]);
  });

  it("records a new entry", () => {
    recordRecentWorkflow({ item_type: "route", label: "Dashboard", route_path: "/dashboard" });
    const all = getRecentWorkflows();
    expect(all).toHaveLength(1);
    expect(all[0].label).toBe("Dashboard");
    expect(all[0].usage_count).toBe(1);
  });

  it("upserts by item_type + route_path + label, bumping usage_count", () => {
    recordRecentWorkflow({ item_type: "route", label: "Dashboard", route_path: "/dashboard" });
    recordRecentWorkflow({ item_type: "route", label: "Dashboard", route_path: "/dashboard" });
    const all = getRecentWorkflows();
    expect(all).toHaveLength(1);
    expect(all[0].usage_count).toBe(2);
  });

  it("never stores admin tokens or arbitrary extra fields", () => {
    recordRecentWorkflow({
      item_type: "admin_action",
      label: "Catalog Ops",
      route_path: "/admin/catalog-ops",
      payload_json: { some_context: "value" },
    });
    const raw = window.localStorage.getItem("optcg.recentWorkflows.v1");
    expect(raw).not.toContain("token");
    expect(raw).not.toContain("admin_token");
  });

  it("caps entries at 20", () => {
    for (let i = 0; i < 25; i++) {
      recordRecentWorkflow({ item_type: "route", label: `Route ${i}`, route_path: `/route-${i}` });
    }
    expect(getRecentWorkflows(100)).toHaveLength(20);
  });
});
