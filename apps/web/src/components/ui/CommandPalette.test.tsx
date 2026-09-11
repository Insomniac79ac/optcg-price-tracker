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
    await screen.findByText("Pages");
    expect(screen.getByText("Home")).toBeInTheDocument();
    expect(screen.getByText("Market")).toBeInTheDocument();
    expect(screen.queryByText("Discover")).not.toBeInTheDocument();
    expect(screen.getByText("Pages")).toBeInTheDocument();
  });

  it("filters commands as the user types", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Pages");

    fireEvent.change(screen.getByPlaceholderText(/search by name or code/i), {
      target: { value: "catalogue" },
    });

    await waitFor(() => expect(screen.getByText("Cards")).toBeInTheDocument());
    expect(screen.queryByText("Home")).not.toBeInTheDocument();
  });

  it("navigates and closes when a command is selected", async () => {
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} />);
    await screen.findByText("Pages");

    fireEvent.click(screen.getByText("Home"));

    expect(push).toHaveBeenCalledWith("/");
    expect(onClose).toHaveBeenCalled();
  });

  it.each([["Home", "/"], ["Cards", "/cards"], ["Market", "/analytics"]])(
    "opens the public %s destination without a lookup",
    async (label, destination) => {
      render(<CommandPalette open onClose={vi.fn()} />);
      fireEvent.click(await screen.findByText(label));
      expect(push).toHaveBeenCalledWith(destination);
      expect(fetchPrintCatalogue).not.toHaveBeenCalled();
    },
  );

  it("closes on Escape", async () => {
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} />);
    await screen.findByText("Pages");

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("does not render admin commands for a signed-out visitor", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Pages");

    fireEvent.change(screen.getByPlaceholderText(/search by name or code/i), {
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
    await screen.findByText("Pages");

    fireEvent.change(screen.getByPlaceholderText(/search by name or code/i), {
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
    await screen.findByText("Pages");

    fireEvent.change(screen.getByPlaceholderText(/search by name or code/i), {
      target: { value: "Catalog Ops" },
    });

    await waitFor(() => expect(screen.getByText("Catalog Ops")).toBeInTheDocument());
  });

  it("hides collector-scoped commands when signed out", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Pages");

    fireEvent.change(screen.getByPlaceholderText(/search by name or code/i), {
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
    await screen.findByText("Pages");

    fireEvent.change(screen.getByPlaceholderText(/search by name or code/i), {
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

  it("looks up cards through the PUBLIC catalogue even when signed in", async () => {
    // Card lookup is catalogue data, identical for every visitor. The
    // authenticated /api/search path searched the legacy `cards` table, whose
    // rows disagree with the catalogue about which card a code names - a
    // signed-in collector was getting narrower AND wrong results.
    useSessionMock.mockReturnValue({
      data: { user: { email: "collector@example.com" } },
      status: "authenticated",
    });
    fetchPrintCatalogue.mockResolvedValue(printList([printItem()]));
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Pages");

    fireEvent.change(screen.getByPlaceholderText(/search by name or code/i), {
      target: { value: "kaido" },
    });

    await waitFor(() => expect(fetchPrintCatalogue).toHaveBeenCalled(), { timeout: 1000 });
    expect(fetchSearch).not.toHaveBeenCalled();
    expect(await screen.findByText("Kaido")).toBeInTheDocument();
  });

  it("does not call card search for a 1-character query", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Pages");

    fireEvent.change(screen.getByPlaceholderText(/search by name or code/i), {
      target: { value: "O" },
    });

    await new Promise((r) => setTimeout(r, 350));
    expect(fetchSearch).not.toHaveBeenCalled();
  });
});

describe("CommandPalette - public card search (signed out)", () => {
  const typeQuery = (value: string) =>
    fireEvent.change(screen.getByPlaceholderText(/search by name or code/i), {
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

  it.each([false, true])("puts cards before matching pages (signed in: %s), with one lookup and uncropped artwork", async (signedIn) => {
    if (signedIn) useSessionMock.mockReturnValue({ data: { user: { email: "a@example.com" } }, status: "authenticated" });
    fetchPrintCatalogue.mockResolvedValue(printList([printItem({ name_en: "Collection card", image_url: "https://example.com/card.png" })]));
    render(<CommandPalette open onClose={vi.fn()} />);
    typeQuery("collection");
    const card = await screen.findByRole("button", { name: /Collection card/ });
    const buttons = screen.getAllByRole("button");
    expect(buttons[0]).toBe(card);
    expect(screen.getByRole("img")).toHaveClass("object-contain");
    expect(screen.getByRole("img").getAttribute("alt")).toContain("printing preview");
    expect(fetchPrintCatalogue).toHaveBeenCalledTimes(1);
    expect(fetchSearch).not.toHaveBeenCalled();
    if (signedIn) expect(screen.getByText("My Collection (Table)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View all results" })).toHaveAttribute("href", "/cards?q=collection");
    expect(screen.queryByText(/\d+ printings/)).not.toBeInTheDocument();
  });

  it("offers encoded durable results even with no suggestions", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    typeQuery("Nami & Luffy");
    await screen.findByText("No matches");
    expect(screen.getByRole("link", { name: "View all results" })).toHaveAttribute("href", "/cards?q=Nami%20%26%20Luffy");
  });

  it("keeps native keyboard activation for View all results", async () => {
    fetchPrintCatalogue.mockResolvedValue(printList([printItem()]));
    render(<CommandPalette open onClose={vi.fn()} />);
    typeQuery("kaido");
    await screen.findByText("Kaido");
    const link = screen.getByRole("link", { name: "View all results" });
    expect(fireEvent.keyDown(link, { key: "Enter" })).toBe(true);
    expect(push).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(push).toHaveBeenCalledWith("/cards/code/OP04-044");
  });

  it("filters private recents on sign-out without deleting local history", async () => {
    const entries = [
      { item_type: "saved_view", label: "Private wish list", route_path: "/wishlist" },
      { item_type: "route", label: "Private report", route_path: "/market/report" },
      { item_type: "admin_action", label: "Private admin", route_path: "/admin/catalog" },
      { item_type: "card", label: "Recent Kaido", route_path: "/cards/code/OP04-044" },
    ].map((entry) => ({ ...entry, payload_json: null, usage_count: 1, last_used_at: "2026-09-11" }));
    const stored = JSON.stringify(entries);
    window.localStorage.setItem("optcg.recentWorkflows.v1", stored);
    useSessionMock.mockReturnValue({ data: { user: {} }, status: "authenticated" });
    const { rerender } = render(<CommandPalette open onClose={vi.fn()} />);
    expect(await screen.findByText("Private wish list")).toBeInTheDocument();
    expect(screen.queryByText("Private admin")).not.toBeInTheDocument();
    useSessionMock.mockReturnValue({ data: null, status: "unauthenticated" });
    rerender(<CommandPalette open onClose={vi.fn()} />);
    expect(screen.queryByText("Private wish list")).not.toBeInTheDocument();
    expect(screen.queryByText("Private report")).not.toBeInTheDocument();
    expect(screen.getByText("Recent Kaido")).toBeInTheDocument();
    expect(window.localStorage.getItem("optcg.recentWorkflows.v1")).toBe(stored);
  });

  it("finds a real print for 'kaido' instead of claiming no matches", async () => {
    fetchPrintCatalogue.mockResolvedValue(printList([printItem()]));
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Pages");

    typeQuery("kaido");

    await waitFor(
      () => expect(fetchPrintCatalogue).toHaveBeenCalledWith({ q: "kaido", limit: 100 }),
      { timeout: 1000 },
    );
    expect(await screen.findByText("Kaido")).toBeInTheDocument();
    expect(screen.queryByText("No matches")).not.toBeInTheDocument();
  });

  it("searches the public catalogue, never the authenticated endpoint", async () => {
    fetchPrintCatalogue.mockResolvedValue(printList([printItem()]));
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Pages");

    fireEvent.change(screen.getByPlaceholderText(/search by name or code/i), {
      target: { value: "kaido" },
    });

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
    await screen.findByText("Pages");

    typeQuery("OP01-001");

    expect(await screen.findByText("Roronoa Zoro")).toBeInTheDocument();
    expect(screen.getAllByText(/OP01-001/).length).toBeGreaterThan(0);
  });

  it("finds a print by Japanese name", async () => {
    fetchPrintCatalogue.mockResolvedValue(printList([printItem()]));
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Pages");

    typeQuery("カイドウ");

    await waitFor(
      () => expect(fetchPrintCatalogue).toHaveBeenCalledWith({ q: "カイドウ", limit: 100 }),
      { timeout: 1000 },
    );
    expect(await screen.findByText("Kaido")).toBeInTheDocument();
  });

  it("navigates to the canonical family route, never a print or a legacy id", async () => {
    // A search result stands for a CARD. Sending the collector to one printing
    // would be choosing for them; the chooser on the family route is where
    // that choice is made.
    fetchPrintCatalogue.mockResolvedValue(
      printList([printItem({ card_print_id: 13, canonical_card_id: 40 })]),
    );
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Pages");

    typeQuery("kaido");
    fireEvent.click(await screen.findByText("Kaido"));

    expect(push).toHaveBeenCalledWith("/cards/code/OP04-044");
    const pushed = push.mock.calls.map(([route]) => route as string);
    expect(pushed.some((route) => route.startsWith("/prints/"))).toBe(false);
    // Never a numeric id from either namespace.
    expect(pushed.some((route) => /^\/cards\/\d+$/.test(route))).toBe(false);
  });

  it("H. collapses base and parallel printings of one card into ONE result", async () => {
    // Previously these were two rows, which made a five-printing card fill the
    // palette by itself. They are one CARD; telling base from parallel is the
    // chooser's job on the family route, not the search list's.
    fetchPrintCatalogue.mockResolvedValue(
      printList([
        printItem({ card_print_id: 13, treatment: "parallel" }),
        printItem({ card_print_id: 14, treatment: "normal" }),
      ]),
    );
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Pages");

    typeQuery("kaido");

    const rows = await screen.findAllByText("Kaido");
    expect(rows).toHaveLength(1);
    // The count is what tells the collector a choice is waiting.
    expect(screen.getByText("OP04-044 · Card family · Choose printing")).toBeInTheDocument();
  });

  it("shows the truthful empty state when the catalogue genuinely has no match", async () => {
    fetchPrintCatalogue.mockResolvedValue(printList([]));
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Pages");

    typeQuery("zzzznotacard");

    await waitFor(() => expect(fetchPrintCatalogue).toHaveBeenCalled(), { timeout: 1000 });
    expect(await screen.findByText("No matches")).toBeInTheDocument();
    expect(screen.queryByText("Search unavailable")).not.toBeInTheDocument();
  });

  it("distinguishes a failed search from an empty one", async () => {
    fetchPrintCatalogue.mockRejectedValue(new Error("network down"));
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Pages");

    typeQuery("kaido");

    expect(await screen.findByText("Search unavailable")).toBeInTheDocument();
    expect(screen.queryByText("No matches")).not.toBeInTheDocument();
  });

  it("still offers the public page commands", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    expect(await screen.findByText("Pages")).toBeInTheDocument();
    expect(screen.getByText("Home")).toBeInTheDocument();
    expect(screen.getByText("Market")).toBeInTheDocument();
    expect(screen.queryByText("Discover")).not.toBeInTheDocument();
    expect(screen.getByText("Cards")).toBeInTheDocument();
  });

  it("no longer offers the retired Market Index page as a command", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Pages");

    expect(screen.queryByText("Market Index")).not.toBeInTheDocument();

    // Including when someone goes looking for it by name - the static list
    // has nothing to offer, and card search must not invent a page result.
    fireEvent.change(screen.getByPlaceholderText(/search by name or code/i), {
      target: { value: "market index" },
    });
    await waitFor(() => expect(screen.queryByText("Market Index")).not.toBeInTheDocument());
  });

  it("does not offer authenticated concepts", async () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    await screen.findByText("Pages");
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
