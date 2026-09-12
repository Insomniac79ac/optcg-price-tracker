import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(() => ({ data: null, status: "unauthenticated" })),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/",
}));

const { fetchSavedViews, fetchCardsCatalogue, apiGet } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  fetchSavedViews: vi.fn().mockResolvedValue({
    items: [],
    pagination: { total: 0, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
  }),
  // Guard: Discover must never reach for the legacy canonical-card catalogue
  // again. That payload carries no print identity, so nothing built from it
  // could link to an exact printing without guessing which one it meant.
  fetchCardsCatalogue: vi.fn(),
}));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, fetchSavedViews, fetchCardsCatalogue, apiGet };
});

const { fetchPrintCatalogue } = vi.hoisted(() => ({ fetchPrintCatalogue: vi.fn() }));
vi.mock("@/lib/prints", async () => {
  const actual = await vi.importActual<typeof import("@/lib/prints")>("@/lib/prints");
  return { ...actual, fetchPrintCatalogue };
});

import type { PrintCatalogueItem } from "@/lib/prints";
import type { IndexMover, IndexMovers } from "@/lib/cardPirateIndex";

import HomePage, { buildCardsSearchHref } from "./page";

/** Shaped on the real `GET /prints` staging payload. `card_print_id` is the
 * only identity this page has, and the only one it may route with. */
function makePrint(
  // `market_index` is spread over the defaults below, so it takes a PARTIAL
  // index - the signature said `PrintMarketIndex` while the body treated it as
  // overrides, which only surfaced once a caller passed one.
  overrides: Partial<Omit<PrintCatalogueItem, "market_index">> & {
    card_print_id: number;
    market_index?: Partial<PrintCatalogueItem["market_index"]>;
  },
): PrintCatalogueItem {
  const { market_index: indexOverrides, ...rest } = overrides;
  return {
    canonical_card_id: 900 + overrides.card_print_id,
    card_code: `OP01-0${overrides.card_print_id}`,
    name_en: `Test Card ${overrides.card_print_id}`,
    name_jp: null,
    rarity: "R",
    card_type: "Character",
    treatment: "normal",
    language: "jp",
    release_product_code: "OP-01",
    image_url: null,
    display_image: null,
    verification_status: "verified",
    source_coverage: [],
    latest_observation_at: null,
    market_index: {
      card_print_id: overrides.card_print_id,
      index_version: 1,
      index_value_jpy: null,
      calculation_method: "median_of_sources",
      source_count: 0,
      coverage_status: "none",
      confidence: "low",
      source_values: [],
      auxiliary_values: [],
      freshest_observation_at: null,
      stalest_eligible_source_at: null,
      stale_sources: [],
      calculated_at: "2026-07-01T00:00:00Z",
      ...indexOverrides,
    },
    ...rest,
  };
}

const catalogueResponse = (items: PrintCatalogueItem[]) => ({
  items,
  total: items.length,
  limit: 100,
  offset: 0,
  pagination: { total: items.length, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
  facets: { treatments: [], rarities: [], languages: [], verification_statuses: [] },
});


const mover = (id: number, overrides: Partial<IndexMover> = {}): IndexMover => ({
  card_print_id: id, card_code: "OP01-001", name: `Mover ${id}`, rarity: "SR",
  display_image_url: `https://www.onepiece-cardgame.com/images/${id}.png`,
  treatment: "parallel", language: "jp", prior_value_jpy: 100, current_value_jpy: 200,
  direction: "up", raw_pct: 30.77, capped_log_return: "0.2231", was_capped: true,
  contribution_log_return: "0.0001", approx_index_points: "0.1000", move_rank: id, impact_rank: id,
  ...overrides,
});
const moves = (overrides: Partial<IndexMovers> = {}): IndexMovers => ({
  as_of: "2026-09-10", prior_point_date: "2026-09-09", constituent_count: 100,
  movers_count: 2, unchanged_count: 98, chain_link_log_return: "0.001", truncated: false,
  movers: [mover(88), mover(2)], ...overrides,
});
beforeEach(() => {
  apiGet.mockReset().mockResolvedValue(moves());
  fetchPrintCatalogue.mockReset().mockResolvedValue(catalogueResponse([makePrint({ card_print_id: 9 })]));
});
afterEach(() => vi.clearAllMocks());
async function ready() {
  render(<HomePage />);
  await screen.findByText("Mover 88");
  await screen.findByText("Test Card 9");
}
const moveSection = () => screen.getByRole("region", { name: "Cards on the move" });
const recentSection = () => screen.getByRole("region", { name: "Recently updated printings" });

describe("Home discovery", () => {
  it("has one catalogue action, compact search and an editorial Market entry", async () => {
    await ready();
    const main = within(screen.getByRole("main"));
    expect(main.getByRole("heading", { level: 1 })).toHaveTextContent("Find your next card.");
    expect(main.getAllByRole("link").filter((a) => a.getAttribute("href") === "/cards")).toHaveLength(1);
    expect(main.getByRole("link", { name: "Browse all cards" })).toHaveAttribute("href", "/cards");
    expect(main.getByRole("link", { name: "See what moved" })).toHaveAttribute("href", "/analytics#latest-moves");
    expect(main.getByRole("link", { name: "View Market →" })).toHaveAttribute("href", "/analytics");
    expect(main.getByRole("heading", { name: "Card Pirate Index" })).toBeInTheDocument();
    expect(main.queryByRole("table")).not.toBeInTheDocument();
    expect(main.queryByText(/Trending|Hot|Opportunities|Newly added|Explore the Atlas|Browse every printing|View full catalogue/)).not.toBeInTheDocument();
  });
  it.each([1, 2, 4])("renders exactly %i supplied movers without decorative slots", async (count) => {
    apiGet.mockResolvedValue(moves({ movers: [88, 2, 91, 7].slice(0, count).map((id) => mover(id)) }));
    await ready();
    expect(within(moveSection()).getAllByRole("listitem")).toHaveLength(count);
    expect(within(moveSection()).getAllByRole("img")).toHaveLength(count);
    expect(within(moveSection()).getByRole("heading", { name: "Cards on the move" })).toHaveAttribute("id", "home-movers");
    expect(within(moveSection()).getByText("01")).toHaveAttribute("aria-hidden", "true");
  });
  it("renders four movers at most, preserving supplied order rather than sorting ranks or prices", async () => {
    apiGet.mockResolvedValue(moves({ movers: [mover(88), mover(2), mover(91), mover(7), mover(1)] }));
    await ready();
    const links = within(moveSection()).getAllByRole("listitem").map((li) => within(li).getByRole("link"));
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/prints/88", "/prints/2", "/prints/91", "/prints/7"]);
  });
  it("keeps duplicate card codes on distinct exact print links and uses payload artwork", async () => {
    await ready();
    for (const id of [88, 2]) {
      const link = within(moveSection()).getByRole("link", { name: new RegExp(`Mover ${id}`) });
      expect(link).toHaveAttribute("href", `/prints/${id}`);
      expect(within(link).getByRole("img")).toHaveAttribute("src", `/api/card-image?u=${encodeURIComponent(`https://www.onepiece-cardgame.com/images/${id}.png`)}`);
      expect(within(link).getByRole("img")).toHaveClass("object-contain");
      expect(link).toHaveClass("focus-visible:outline-2");
      expect(link.querySelector("button, a")).toBeNull();
    }
  });
  it("does not need a card code to open an exact printing", async () => {
    apiGet.mockResolvedValue(moves({ movers: [mover(88, { card_code: null })] }));
    await ready();
    expect(within(moveSection()).getByRole("link", { name: /Mover 88/ })).toHaveAttribute("href", "/prints/88");
  });
  it("formats the server raw move without deriving it from prices or the cap", async () => {
    await ready();
    expect(within(moveSection()).getAllByText("+30.77%")).toHaveLength(2);
    expect(within(moveSection()).queryByText("+100.00%")).not.toBeInTheDocument();
    expect(within(moveSection()).queryByText("+25.00%")).not.toBeInTheDocument();
    expect(within(moveSection()).getByText("Sep 10, 2026")).toBeInTheDocument();
  });
  it("uses exactly one catalogue and one movers request, with no per-card requests on rerender", async () => {
    await ready();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "OP01-001" } });
    fireEvent.focus(within(moveSection()).getByRole("link", { name: /Mover 88/ }));
    expect(fetchPrintCatalogue).toHaveBeenCalledExactlyOnceWith({ sort: "updated", limit: 100 });
    expect(apiGet).toHaveBeenCalledExactlyOnceWith("/analytics/index/movers");
    expect(fetchCardsCatalogue).not.toHaveBeenCalled();
  });
  it("shows an accessible loading state", () => {
    apiGet.mockReturnValue(new Promise(() => {}));
    render(<HomePage />);
    expect(screen.getByRole("status", { name: "Loading cards on the move" })).toBeInTheDocument();
  });
  it.each([
    ["zero", moves({ movers: [], movers_count: 0 }), "No cards moved on this published day."],
    ["base", moves({ movers: [], prior_point_date: null }), "The latest index update has no previous point to compare."],
  ])("handles %s movers honestly without replacement cards", async (_, payload, copy) => {
    apiGet.mockResolvedValue(payload);
    render(<HomePage />);
    expect(await screen.findByText(copy as string)).toBeInTheDocument();
    expect(within(moveSection()).queryByRole("list")).not.toBeInTheDocument();
    expect(await screen.findByText("Test Card 9")).toBeInTheDocument();
  });
  it("keeps catalogue discovery available if movers are unavailable", async () => {
    apiGet.mockRejectedValue(new Error("offline"));
    render(<HomePage />);
    expect(await screen.findByText("We can’t show the cards on the move right now.")).toBeInTheDocument();
    expect(await screen.findByText("Test Card 9")).toBeInTheDocument();
    expect(within(moveSection()).queryByRole("list")).not.toBeInTheDocument();
  });
  it("retains priced-first selection within recently updated records only", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([1, 2, 3, 4, 5].map((id) => makePrint({card_print_id: id, market_index: {index_value_jpy: id === 3 || id === 5 ? 100 : null}}))));
    render(<HomePage />);
    await screen.findByText("Test Card 3");
    expect(within(recentSection()).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual(["/prints/3", "/prints/5", "/prints/1", "/prints/2"]);
  });
  it("keeps recently updated sibling printings directly openable", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([makePrint({card_print_id: 9, card_code: "OP01-001"}), makePrint({card_print_id: 10, card_code: "OP01-001"})]));
    await ready();
    expect(within(recentSection()).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual(["/prints/9", "/prints/10"]);
  });
  it("does not add another catalogue CTA when the catalogue is empty", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<HomePage />);
    expect(await screen.findByText("No recently updated printings are available right now.")).toBeInTheDocument();
    expect(within(screen.getByRole("main")).getAllByRole("link", { name: "Browse all cards" })).toHaveLength(1);
  });
  it("retries the catalogue independently without refetching movers", async () => {
    fetchPrintCatalogue.mockRejectedValueOnce(new Error("offline"));
    render(<HomePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    await screen.findByText("Test Card 9");
    expect(fetchPrintCatalogue).toHaveBeenCalledTimes(2);
    expect(apiGet).toHaveBeenCalledTimes(1);
  });
});

describe("Home search", () => {
  it.each(["Kaido", "OP01-001", "カイドウ", "  Kaido  ", "", "   "])("submits %s to public Cards without lookup requests", async (term) => {
    await ready();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search cards by name or code" }), { target: { value: term } });
    fireEvent.submit(screen.getByRole("search"));
    expect(push).toHaveBeenCalledWith(term.trim() ? `/cards?q=${encodeURIComponent(term.trim())}` : "/cards");
    expect(apiGet).toHaveBeenCalledTimes(1);
    expect(fetchPrintCatalogue).toHaveBeenCalledTimes(1);
  });
  it("has a visible submit control in the same responsive form", async () => {
    await ready();
    fireEvent.change(screen.getByRole("searchbox"), {target: {value: "OP01-001"}});
    fireEvent.click(within(screen.getByRole("search")).getByRole("button", {name: "Search"}));
    expect(push).toHaveBeenCalledWith("/cards?q=OP01-001");
    expect(screen.getAllByRole("search")).toHaveLength(1);
  });
  it("bounds the query to the catalogue's existing limit", () => {
    expect(buildCardsSearchHref("a".repeat(200))).toBe(`/cards?q=${"a".repeat(128)}`);
  });
});
