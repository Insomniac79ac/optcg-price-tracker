import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/dashboard",
}));

const useSessionMock = vi.fn();
vi.mock("next-auth/react", () => ({
  useSession: () => useSessionMock(),
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
    useSessionMock.mockReturnValue({ data: null, status: "unauthenticated" });
  });

  it("renders nothing when closed", () => {
    const { container } = render(<CommandPalette open={false} onClose={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders static public commands when open, grouped under Commands", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());
    expect(screen.getByText("Discover")).toBeInTheDocument();
    expect(screen.getByText("Commands")).toBeInTheDocument();
  });

  it("filters commands as the user types", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText(/search cards and pages/i), {
      target: { value: "market index" },
    });

    await waitFor(() => expect(screen.getByText("Market Index")).toBeInTheDocument());
    expect(screen.queryByText("Discover")).not.toBeInTheDocument();
  });

  it("navigates and closes when a command is selected", async () => {
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} />);
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());

    fireEvent.click(screen.getByText("Discover"));

    expect(push).toHaveBeenCalledWith("/");
    expect(onClose).toHaveBeenCalled();
  });

  it("closes on Escape", async () => {
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} />);
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("does not render admin commands for a signed-out visitor", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText(/search cards and pages/i), {
      target: { value: "Catalog Ops" },
    });

    // No results at all - the admin command is filtered out before the
    // text search even runs against it, not merely hidden behind a badge.
    await waitFor(() => expect(screen.getByText(/no matches/i)).toBeInTheDocument());
    expect(screen.queryByText("Catalog Ops")).not.toBeInTheDocument();
    expect(screen.queryByText("ADMIN")).not.toBeInTheDocument();
  });

  it("does not render admin commands even for an authenticated collector session", async () => {
    useSessionMock.mockReturnValue({
      data: { user: { email: "collector@example.com" } },
      status: "authenticated",
    });
    render(<CommandPalette open onClose={vi.fn()} />);
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText(/search cards and pages/i), {
      target: { value: "Catalog Ops" },
    });

    await waitFor(() => expect(screen.getByText(/no matches/i)).toBeInTheDocument());
    expect(screen.queryByText("Catalog Ops")).not.toBeInTheDocument();
  });

  it("renders admin commands for a role=admin session", async () => {
    useSessionMock.mockReturnValue({
      data: { user: { email: "admin@example.com", role: "admin" } },
      status: "authenticated",
    });
    render(<CommandPalette open onClose={vi.fn()} />);
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText(/search cards and pages/i), {
      target: { value: "Catalog Ops" },
    });

    await waitFor(() => expect(screen.getByText("Catalog Ops")).toBeInTheDocument());
  });

  it("hides collector-scoped commands when signed out", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText(/search cards and pages/i), {
      target: { value: "wishlist" },
    });

    await waitFor(() => expect(screen.getByText(/no matches/i)).toBeInTheDocument());
    expect(screen.queryByText("Wishlist")).not.toBeInTheDocument();
  });

  it("shows collector-scoped commands once a session exists", async () => {
    useSessionMock.mockReturnValue({
      data: { user: { email: "collector@example.com" } },
      status: "authenticated",
    });
    render(<CommandPalette open onClose={vi.fn()} />);
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText(/search cards and pages/i), {
      target: { value: "wishlist" },
    });

    await waitFor(() => expect(screen.getByText("Wishlist")).toBeInTheDocument());
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

    fireEvent.change(screen.getByPlaceholderText(/search cards and pages/i), {
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

    fireEvent.change(screen.getByPlaceholderText(/search cards and pages/i), {
      target: { value: "O" },
    });

    await new Promise((r) => setTimeout(r, 350));
    expect(fetchSearch).not.toHaveBeenCalled();
  });
});
