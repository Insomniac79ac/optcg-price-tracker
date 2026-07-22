import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/dashboard",
}));

const fetchSavedViews = vi.fn();
const fetchSearch = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchSavedViews: (...args: unknown[]) => fetchSavedViews(...args),
    fetchSearch: (...args: unknown[]) => fetchSearch(...args),
  };
});

import { CommandPalette } from "./CommandPalette";

const EMPTY_SAVED_VIEWS = {
  items: [],
  pagination: { total: 0, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
};

const EMPTY_SEARCH = {
  query: "",
  summary: { total_results: 0, by_type: {} },
  results: [],
  limit: 8,
  offset: 0,
  pagination: { total: 0, limit: 8, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
};

describe("CommandPalette", () => {
  beforeEach(() => {
    push.mockReset();
    fetchSavedViews.mockReset().mockResolvedValue(EMPTY_SAVED_VIEWS);
    fetchSearch.mockReset().mockResolvedValue(EMPTY_SEARCH);
    window.localStorage.clear();
  });

  it("renders nothing when closed", () => {
    const { container } = render(<CommandPalette open={false} onClose={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders static commands when open, grouped under Commands", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Commands")).toBeInTheDocument();
  });

  it("filters commands as the user types", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText(/search pages, cards, saved views/i), {
      target: { value: "wishlist" },
    });

    await waitFor(() => expect(screen.getByText("Wishlist")).toBeInTheDocument());
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();
  });

  it("navigates and closes when a command is selected", async () => {
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} />);
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());

    fireEvent.click(screen.getByText("Dashboard"));

    expect(push).toHaveBeenCalledWith("/dashboard");
    expect(onClose).toHaveBeenCalled();
  });

  it("closes on Escape", async () => {
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} />);
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("shows the admin badge for admin commands", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText(/search pages, cards, saved views/i), {
      target: { value: "Catalog Ops" },
    });

    await waitFor(() => expect(screen.getByText("Catalog Ops")).toBeInTheDocument());
    expect(screen.getByText("ADMIN")).toBeInTheDocument();
  });

  it("renders saved views under a Saved Views group", async () => {
    fetchSavedViews.mockResolvedValue({
      items: [
        {
          id: 1,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
          name: "Grail Buys",
          description: null,
          route_path: "/analytics/buy-decisions",
          view_type: "buy_decisions",
          scope: "analytics",
          filters_json: null,
          sort_json: null,
          columns_json: null,
          density: "compact",
          is_default: false,
          pinned: true,
          last_used_at: null,
          usage_count: 0,
          notes: null,
        },
      ],
      pagination: { total: 1, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
    });

    render(<CommandPalette open onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Grail Buys")).toBeInTheDocument());
    expect(screen.getByText("Saved Views")).toBeInTheDocument();
  });

  it("looks up cards once the query is at least 2 characters", async () => {
    fetchSearch.mockResolvedValue({
      ...EMPTY_SEARCH,
      results: [
        {
          type: "cards",
          id: 1,
          score: 1,
          title: "OP01-001 Monkey D. Luffy",
          subtitle: "Leader",
          matched_fields: ["card_code"],
          card_id: 1,
          card_code: "OP01-001",
          name_en: "Monkey D. Luffy",
          name_jp: null,
          url: "/cards/1",
          metadata: {},
        },
      ],
    });

    render(<CommandPalette open onClose={vi.fn()} />);
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText(/search pages, cards, saved views/i), {
      target: { value: "OP01" },
    });

    await waitFor(() => expect(fetchSearch).toHaveBeenCalledWith({ q: "OP01", types: ["cards"], limit: 8 }), {
      timeout: 1000,
    });
    await waitFor(() => expect(screen.getByText("OP01-001 Monkey D. Luffy")).toBeInTheDocument());
  });

  it("does not call card search for a 1-character query", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText(/search pages, cards, saved views/i), {
      target: { value: "O" },
    });

    await new Promise((r) => setTimeout(r, 350));
    expect(fetchSearch).not.toHaveBeenCalled();
  });
});
