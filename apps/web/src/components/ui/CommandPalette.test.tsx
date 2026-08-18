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

// The public catalogue search a signed-out palette uses. toPrintUiModel stays
// real so the rows are built by the same mapping /cards renders from.
const fetchPrintCatalogue = vi.fn();
vi.mock("@/lib/prints", async () => {
  const actual = await vi.importActual<typeof import("@/lib/prints")>("@/lib/prints");
  return {
    ...actual,
    fetchPrintCatalogue: (...args: unknown[]) => fetchPrintCatalogue(...args),
  };
});

import { CommandPalette } from "./CommandPalette";

const EMPTY_SAVED_VIEWS = {
  items: [],
  pagination: { total: 0, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
};

/** One GET /prints item, shaped as the catalogue really returns it. */
function printItem(overrides: Record<string, unknown> = {}) {
  return {
    card_print_id: 13,
    canonical_card_id: 40,
    card_code: "OP04-044",
    name_en: "Kaido",
    name_jp: "カイドウ",
    rarity: "SR",
    card_type: "Character",
    treatment: "parallel",
    language: "jp",
    release_product_code: "OP-04",
    image_url: null,
    display_image: null,
    verification_status: "verified",
    source_coverage: [],
    latest_observation_at: null,
    market_index: {
      card_print_id: 13,
      index_version: 1,
      index_value_jpy: 1040,
      calculation_method: "median",
      source_count: 1,
      coverage_status: "limited",
      confidence: "medium",
      source_values: [],
      auxiliary_values: [],
      freshest_observation_at: null,
      stalest_eligible_source_at: null,
      stale_sources: [],
      calculated_at: "2026-08-18T00:00:00Z",
    },
    ...overrides,
  };
}

function printList(items: ReturnType<typeof printItem>[]) {
  return {
    items,
    total: items.length,
    limit: 8,
    offset: 0,
    pagination: {
      total: items.length,
      limit: 8,
      offset: 0,
      has_next: false,
      has_previous: false,
      next_offset: null,
      previous_offset: null,
    },
    facets: { treatments: [], rarities: [], languages: [], verification_statuses: [] },
  };
}

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
    fetchPrintCatalogue.mockReset().mockResolvedValue(printList([]));
    window.localStorage.clear();
    useSessionMock.mockReturnValue({ data: null, status: "unauthenticated" });
  });

  it("renders nothing when closed", () => {
    const { container } = render(<CommandPalette open={false} onClose={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders static public commands when open, grouped under Commands", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Commands");
    expect(screen.getByText("Discover")).toBeInTheDocument();
    expect(screen.getByText("Commands")).toBeInTheDocument();
  });

  it("filters commands as the user types", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Commands");

    fireEvent.change(screen.getByPlaceholderText(/search cards and pages/i), {
      target: { value: "market index" },
    });

    await waitFor(() => expect(screen.getByText("Market Index")).toBeInTheDocument());
    expect(screen.queryByText("Discover")).not.toBeInTheDocument();
  });

  it("navigates and closes when a command is selected", async () => {
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} />);
    await screen.findByText("Commands");

    fireEvent.click(screen.getByText("Discover"));

    expect(push).toHaveBeenCalledWith("/");
    expect(onClose).toHaveBeenCalled();
  });

  it("closes on Escape", async () => {
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} />);
    await screen.findByText("Commands");

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("does not render admin commands for a signed-out visitor", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Commands");

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
    await screen.findByText("Commands");

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
    await screen.findByText("Commands");

    fireEvent.change(screen.getByPlaceholderText(/search cards and pages/i), {
      target: { value: "Catalog Ops" },
    });

    await waitFor(() => expect(screen.getByText("Catalog Ops")).toBeInTheDocument());
  });

  it("hides collector-scoped commands when signed out", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Commands");

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
    await screen.findByText("Commands");

    fireEvent.change(screen.getByPlaceholderText(/search cards and pages/i), {
      target: { value: "wishlist" },
    });

    await waitFor(() => expect(screen.getByText("Wishlist")).toBeInTheDocument());
  });

  it("renders saved views under a Saved Views group", async () => {
    // Saved views are per-collector, so this is a signed-in scenario.
    useSessionMock.mockReturnValue({
      data: { user: { email: "collector@example.com" } },
      status: "authenticated",
    });
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

  it("looks up cards through the authenticated search when signed in", async () => {
    useSessionMock.mockReturnValue({
      data: { user: { email: "collector@example.com" } },
      status: "authenticated",
    });
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
    await screen.findByText("Commands");

    fireEvent.change(screen.getByPlaceholderText(/search cards and pages/i), {
      target: { value: "OP01" },
    });

    await waitFor(() => expect(fetchSearch).toHaveBeenCalledWith({ q: "OP01", types: ["cards"], limit: 8 }), {
      timeout: 1000,
    });
    await waitFor(() => expect(screen.getByText("OP01-001 Monkey D. Luffy")).toBeInTheDocument());
    expect(fetchPrintCatalogue).not.toHaveBeenCalled();
  });

  it("does not call card search for a 1-character query", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Commands");

    fireEvent.change(screen.getByPlaceholderText(/search cards and pages/i), {
      target: { value: "O" },
    });

    await new Promise((r) => setTimeout(r, 350));
    expect(fetchSearch).not.toHaveBeenCalled();
  });
});

describe("CommandPalette - public card search (signed out)", () => {
  const typeQuery = (value: string) =>
    fireEvent.change(screen.getByPlaceholderText(/search cards and pages/i), {
      target: { value },
    });

  beforeEach(() => {
    push.mockReset();
    fetchSavedViews.mockReset().mockResolvedValue(EMPTY_SAVED_VIEWS);
    fetchSearch.mockReset().mockResolvedValue(EMPTY_SEARCH);
    fetchPrintCatalogue.mockReset().mockResolvedValue(printList([]));
    window.localStorage.clear();
    useSessionMock.mockReturnValue({ data: null, status: "unauthenticated" });
  });

  it("finds a real print for 'kaido' instead of claiming no matches", async () => {
    fetchPrintCatalogue.mockResolvedValue(printList([printItem()]));
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Commands");

    typeQuery("kaido");

    await waitFor(
      () => expect(fetchPrintCatalogue).toHaveBeenCalledWith({ q: "kaido", limit: 8 }),
      { timeout: 1000 },
    );
    expect(await screen.findByText("Kaido")).toBeInTheDocument();
    expect(screen.queryByText("No matches")).not.toBeInTheDocument();
  });

  it("searches the public catalogue, never the authenticated endpoint", async () => {
    fetchPrintCatalogue.mockResolvedValue(printList([printItem()]));
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Commands");

    typeQuery("kaido");

    await waitFor(() => expect(fetchPrintCatalogue).toHaveBeenCalled(), { timeout: 1000 });
    expect(fetchSearch).not.toHaveBeenCalled();
    expect(fetchSavedViews).not.toHaveBeenCalled();
  });

  it("finds a print by card code", async () => {
    fetchPrintCatalogue.mockResolvedValue(
      printList([
        printItem({
          card_print_id: 1,
          card_code: "OP01-001",
          name_en: "Roronoa Zoro",
          name_jp: "ロロノア・ゾロ",
          treatment: "parallel",
          release_product_code: "OP-01",
        }),
      ]),
    );
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Commands");

    typeQuery("OP01-001");

    expect(await screen.findByText("Roronoa Zoro")).toBeInTheDocument();
    expect(screen.getByText(/OP01-001/)).toBeInTheDocument();
  });

  it("finds a print by Japanese name", async () => {
    fetchPrintCatalogue.mockResolvedValue(printList([printItem()]));
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Commands");

    typeQuery("カイドウ");

    await waitFor(
      () => expect(fetchPrintCatalogue).toHaveBeenCalledWith({ q: "カイドウ", limit: 8 }),
      { timeout: 1000 },
    );
    expect(await screen.findByText("Kaido")).toBeInTheDocument();
  });

  it("navigates to /prints/{card_print_id}, never a card_id URL", async () => {
    // canonical_card_id deliberately differs from card_print_id so a mix-up
    // would be visible rather than coincidentally correct.
    fetchPrintCatalogue.mockResolvedValue(
      printList([printItem({ card_print_id: 13, canonical_card_id: 40 })]),
    );
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Commands");

    typeQuery("kaido");
    fireEvent.click(await screen.findByText("Kaido"));

    expect(push).toHaveBeenCalledWith("/prints/13");
    const pushed = push.mock.calls.map(([route]) => route as string);
    expect(pushed.some((route) => route.startsWith("/cards/"))).toBe(false);
    expect(pushed).not.toContain("/prints/40");
  });

  it("keeps base and parallel printings of one card distinguishable", async () => {
    fetchPrintCatalogue.mockResolvedValue(
      printList([
        printItem({ card_print_id: 13, treatment: "parallel" }),
        printItem({ card_print_id: 14, treatment: "normal" }),
      ]),
    );
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Commands");

    typeQuery("kaido");

    const rows = await screen.findAllByText("Kaido");
    expect(rows).toHaveLength(2);
    // The parallel printing names its treatment; the base printing does not,
    // so the two subtitles differ.
    expect(screen.getByText(/OP04-044 · OP-04 · parallel/)).toBeInTheDocument();
    expect(screen.getByText(/^OP04-044 · OP-04$/)).toBeInTheDocument();
  });

  it("shows the truthful empty state when the catalogue genuinely has no match", async () => {
    fetchPrintCatalogue.mockResolvedValue(printList([]));
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Commands");

    typeQuery("zzzznotacard");

    await waitFor(() => expect(fetchPrintCatalogue).toHaveBeenCalled(), { timeout: 1000 });
    expect(await screen.findByText("No matches")).toBeInTheDocument();
    expect(screen.queryByText("Search unavailable")).not.toBeInTheDocument();
  });

  it("distinguishes a failed search from an empty one", async () => {
    fetchPrintCatalogue.mockRejectedValue(new Error("network down"));
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Commands");

    typeQuery("kaido");

    expect(await screen.findByText("Search unavailable")).toBeInTheDocument();
    expect(screen.queryByText("No matches")).not.toBeInTheDocument();
  });

  it("still offers the public page commands", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    expect(await screen.findByText("Commands")).toBeInTheDocument();
    expect(screen.getByText("Discover")).toBeInTheDocument();
    expect(screen.getByText("Cards")).toBeInTheDocument();
    expect(screen.getByText("Market Index")).toBeInTheDocument();
  });

  it("does not offer authenticated concepts", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Commands");
    for (const label of [
      /^Collection$/,
      /^Wishlist$/,
      /^Grading$/,
      /^Dashboard$/,
      /^Saved Views$/,
    ]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });
});
