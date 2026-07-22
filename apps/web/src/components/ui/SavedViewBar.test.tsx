import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchSavedViews = vi.fn();
const createSavedView = vi.fn();
const updateSavedView = vi.fn();
const deleteSavedView = vi.fn();
const markSavedViewUsed = vi.fn();
const setDefaultSavedView = vi.fn();
const clearDefaultSavedView = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchSavedViews: (...args: unknown[]) => fetchSavedViews(...args),
    createSavedView: (...args: unknown[]) => createSavedView(...args),
    updateSavedView: (...args: unknown[]) => updateSavedView(...args),
    deleteSavedView: (...args: unknown[]) => deleteSavedView(...args),
    markSavedViewUsed: (...args: unknown[]) => markSavedViewUsed(...args),
    setDefaultSavedView: (...args: unknown[]) => setDefaultSavedView(...args),
    clearDefaultSavedView: (...args: unknown[]) => clearDefaultSavedView(...args),
  };
});

import { AdminAuthRequiredError } from "@/lib/api";
import { SavedViewBar } from "./SavedViewBar";

const EMPTY_LIST = {
  items: [],
  pagination: { total: 0, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
};

function listWith(items: unknown[]) {
  return {
    items,
    pagination: { total: items.length, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
  };
}

const SAVED_VIEW = {
  id: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  name: "Review Buy",
  description: "Review buy candidates",
  route_path: "/analytics/buy-decisions",
  view_type: "buy_decisions",
  scope: "analytics" as const,
  filters_json: { action: "review_buy", min_score: 70 },
  sort_json: null,
  columns_json: null,
  density: "compact" as const,
  is_default: false,
  pinned: false,
  last_used_at: null,
  usage_count: 0,
  notes: null,
};

describe("SavedViewBar", () => {
  beforeEach(() => {
    fetchSavedViews.mockReset();
    createSavedView.mockReset();
    updateSavedView.mockReset();
    deleteSavedView.mockReset();
    markSavedViewUsed.mockReset();
    setDefaultSavedView.mockReset();
    clearDefaultSavedView.mockReset();
  });

  it("renders an empty saved-views dropdown when there are none yet", async () => {
    fetchSavedViews.mockResolvedValue(EMPTY_LIST);
    render(
      <SavedViewBar
        routePath="/analytics/buy-decisions"
        viewType="buy_decisions"
        scope="analytics"
        currentFilters={{ action: "review_buy" }}
        onApply={vi.fn()}
      />,
    );

    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalledWith({
      route_path: "/analytics/buy-decisions",
      view_type: "buy_decisions",
    }));
    expect(screen.getByRole("button", { name: "Save current view" })).toBeInTheDocument();
  });

  it("saves the current filters as a new named view", async () => {
    fetchSavedViews.mockResolvedValue(EMPTY_LIST);
    createSavedView.mockResolvedValue(SAVED_VIEW);
    render(
      <SavedViewBar
        routePath="/analytics/buy-decisions"
        viewType="buy_decisions"
        scope="analytics"
        currentFilters={{ action: "review_buy", min_score: 70 }}
        onApply={vi.fn()}
      />,
    );
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Save current view" }));
    fireEvent.change(screen.getByPlaceholderText("e.g. Review Buy"), {
      target: { value: "Review Buy" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(createSavedView).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Review Buy",
        route_path: "/analytics/buy-decisions",
        view_type: "buy_decisions",
        filters_json: { action: "review_buy", min_score: 70 },
      }),
    ));

    // The saved payload must never include an admin token or any
    // token/secret/confirm-like key, regardless of what page this bar is
    // mounted on (admin pages included).
    const savedBody = createSavedView.mock.calls[0][0];
    const keys = Object.keys(savedBody.filters_json ?? {}).map((k) => k.toLowerCase());
    expect(keys.some((k) => k.includes("token") || k.includes("secret") || k.includes("confirm"))).toBe(false);
    expect(JSON.stringify(savedBody)).not.toMatch(/x-admin-token/i);
  });

  it("applies a saved view by calling onApply with its filters_json", async () => {
    fetchSavedViews.mockResolvedValue(listWith([SAVED_VIEW]));
    markSavedViewUsed.mockResolvedValue(SAVED_VIEW);
    const onApply = vi.fn();
    render(
      <SavedViewBar
        routePath="/analytics/buy-decisions"
        viewType="buy_decisions"
        scope="analytics"
        currentFilters={{}}
        onApply={onApply}
      />,
    );
    await waitFor(() => expect(screen.getByText("Review Buy")).toBeInTheDocument());

    fireEvent.change(screen.getByRole("combobox"), { target: { value: String(SAVED_VIEW.id) } });

    expect(onApply).toHaveBeenCalledWith({ action: "review_buy", min_score: 70 });
    await waitFor(() => expect(markSavedViewUsed).toHaveBeenCalledWith(SAVED_VIEW.id));
  });

  it("shows a sign-in prompt instead of crashing when unauthenticated", async () => {
    fetchSavedViews.mockRejectedValue(new AdminAuthRequiredError());
    render(
      <SavedViewBar
        routePath="/admin/source-mapping-quality"
        viewType="source_mapping_quality"
        scope="admin"
        currentFilters={{}}
        onApply={vi.fn()}
      />,
    );

    await waitFor(() =>
      expect(screen.getByText("Sign in to use saved views on this page.")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: "Save current view" })).not.toBeInTheDocument();
  });
});
