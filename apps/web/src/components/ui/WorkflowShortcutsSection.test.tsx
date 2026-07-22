import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { WorkflowShortcutsSection } from "./WorkflowShortcutsSection";

describe("WorkflowShortcutsSection", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders the static shortcut pills with no recent history", () => {
    render(<WorkflowShortcutsSection />);
    expect(screen.getByText("Workflow Shortcuts")).toBeInTheDocument();
    expect(screen.getByText("Buy Decisions")).toBeInTheDocument();
    expect(screen.getByText("Catalog Ops")).toBeInTheDocument();
  });

  it("renders recent workflow entries from localStorage", () => {
    window.localStorage.setItem(
      "optcg.recentWorkflows.v1",
      JSON.stringify([
        {
          item_type: "route",
          label: "Sell Decisions",
          route_path: "/analytics/sell-decisions",
          payload_json: null,
          last_used_at: "2026-01-01T00:00:00Z",
          usage_count: 1,
        },
      ]),
    );

    render(<WorkflowShortcutsSection />);
    expect(screen.getAllByText("Sell Decisions").length).toBeGreaterThan(0);
  });
});
