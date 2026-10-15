import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
const { authMock, loadCollectionPage, readPrint, refresh } = vi.hoisted(() => ({
  authMock: vi.fn(),
  loadCollectionPage: vi.fn(),
  readPrint: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ auth: authMock }));
vi.mock("@/lib/collectionServer", () => ({ loadCollectionPage }));
vi.mock("@/lib/publicServer", () => ({ readPrint }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh }), usePathname: () => "/collection" }));
vi.mock("@/components/AppHeader", () => ({ AppHeader: () => <header data-testid="app-header" /> }));

import type { CollectionEntry, CollectionValue, CollectionWindow, Coverage } from "@/lib/collection";

import CollectionPage from "./page";

const COLLECTOR = { user: { id: "google-123", email: "nami@example.com", name: "Nami" }, sessionKind: "collector" };

const summaryOf = (over: Partial<Coverage> = {}): Coverage => ({
  value_jpy: 41200,
  priced_cards: 3,
  total_cards: 5,
  priced_entries: 2,
  total_entries: 4,
  unresolved_entries: 1,
  coverage_pct: "60.00",
  ...over,
});

const print = (id: number, code: string, name: string, release = "OP-05") => ({
  card_print_id: id,
  card_code: code,
  name_en: name,
  name_jp: null,
  treatment: "normal",
  official_asset_variant: "base",
  release_product_id: 205,
  release_code: release,
  release_name: "Awakening of the New Era",
});

const ENTRIES: CollectionEntry[] = [
  { id: 1, card_print_id: 101, resolution: "exact", quantity: 2, paid_jpy_per_card: 15000, acquired_on: "2026-06-02", note: null, legacy_card_id: null, print: print(101, "OP05-119", "Monkey.D.Luffy"), value_status: "priced", value_per_card_jpy: 19800, value_jpy: 39600 },
  { id: 2, card_print_id: 104, resolution: "exact", quantity: 1, paid_jpy_per_card: null, acquired_on: null, note: null, legacy_card_id: null, print: print(104, "OP01-120", "Shanks", "OP-01"), value_status: "priced", value_per_card_jpy: 1600, value_jpy: 1600 },
  { id: 3, card_print_id: 103, resolution: "exact", quantity: 1, paid_jpy_per_card: null, acquired_on: null, note: null, legacy_card_id: null, print: print(103, "OP05-119", "Monkey.D.Luffy"), value_status: "no_price", value_per_card_jpy: null, value_jpy: null },
  { id: 4, card_print_id: null, resolution: "unresolved", quantity: 1, paid_jpy_per_card: 500, acquired_on: null, note: "Imported from the old collection", legacy_card_id: 2, print: null, value_status: "unresolved", value_per_card_jpy: null, value_jpy: null },
];

const step = (available: boolean, reason: string | null = null, change_pct: string | null = available ? "2.40" : null) => ({
  available,
  reason,
  from_date: "2026-10-07",
  to_date: "2026-10-14",
  missing_dates: [],
  comparable_cards: available ? 3 : 0,
  change_jpy: available ? 960 : null,
  change_pct,
});

function valueFor(window: CollectionWindow, available: boolean): CollectionValue {
  const s = step(available, available ? null : "not_enough_price_history");
  return {
    as_of: "2026-10-14",
    window,
    summary: summaryOf(),
    movers: {
      ...s,
      up: available ? [{ card_print_id: 101, units: 2, prior_value_per_card_jpy: 19320, current_value_per_card_jpy: 19800, delta_jpy: 960, change_pct: "2.48", contribution_pct_points: "2.4" }] : [],
      down: available ? [{ card_print_id: 104, units: 1, prior_value_per_card_jpy: 1650, current_value_per_card_jpy: 1600, delta_jpy: -50, change_pct: "-3.03", contribution_pct_points: "-0.1" }] : [],
    },
    cards: available
      ? [
          { card_print_id: 101, units: 2, prior_value_per_card_jpy: 19320, current_value_per_card_jpy: 19800, delta_jpy: 960, change_pct: "2.48", contribution_pct_points: "2.4" },
          { card_print_id: 104, units: 1, prior_value_per_card_jpy: 1650, current_value_per_card_jpy: 1600, delta_jpy: -50, change_pct: "-3.03", contribution_pct_points: "-0.1" },
        ]
      : [],
    by_release: [
      { release_product_id: 205, release_code: "OP-05", release_name: "Awakening of the New Era", value_jpy: 39600, priced_cards: 2, total_cards: 3, share_pct: "96.12", change: s },
      { release_product_id: 201, release_code: "OP-01", release_name: "Romance Dawn", value_jpy: 1600, priced_cards: 1, total_cards: 1, share_pct: "3.88", change: step(false, "insufficient_comparable_value_coverage") },
    ],
    paid: { cards_with_paid: 2, cards_compared: 2, total_cards: 5, paid_jpy: 30000, priced_today_jpy: 39600, change_pct: "32.00" },
    history: {
      change: { window, available, reason: available ? null : "not_enough_history", from_date: "2026-10-07", to_date: "2026-10-14", change_pct: available ? "3.02" : null, missing_dates: [] },
      points: [
        { date: "2026-10-13", value_jpy: 40000 },
        { date: "2026-10-14", value_jpy: 41200 },
      ],
    },
    preview: {
      label: "Preview: how the cards you hold now moved over the last 30 days. This is not your collection's recorded history.",
      change: { window: "30d", available: true, reason: null, from_date: "2026-09-15", to_date: "2026-10-14", change_pct: "5.00", missing_dates: [] },
      points: [
        { date: "2026-09-15", value_jpy: 39000 },
        { date: "2026-10-14", value_jpy: 41200 },
      ],
    },
  };
}

function okPage(over: { entries?: CollectionEntry[]; summary?: Coverage; values?: Partial<Record<CollectionWindow, CollectionValue | null>> } = {}) {
  return {
    state: "ok",
    collection: { as_of: "2026-10-14", summary: over.summary ?? summaryOf(), entries: over.entries ?? ENTRIES },
    values: { "7d": valueFor("7d", true), "30d": valueFor("30d", false), all: valueFor("all", true), ...over.values },
  };
}

async function renderPage(window?: string) {
  return render(await CollectionPage({ searchParams: Promise.resolve(window ? { window } : {}) }));
}

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("/collection (Collector v1 S7)", () => {
  it("leads with the value, its date and its coverage", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadCollectionPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    await renderPage();

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("41,200");
    expect(screen.getByText(/Prices as of 14 Oct/)).toBeInTheDocument();
    expect(screen.getByTestId("collection-coverage")).toHaveTextContent("Priced: 3 of 5 cards (60%)");
    expect(screen.getByText(/never counted as ¥0/)).toBeInTheDocument();
    expect(loadCollectionPage).toHaveBeenCalledWith({ sub: "google-123", email: "nami@example.com", name: "Nami" });
  });

  it("keeps the PLAN order: chips, history, moved, by set, cards, paid, needs a version", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadCollectionPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    const { container } = await renderPage();
    const headings = [...container.querySelectorAll("h2")].map((h) => h.textContent);
    expect(headings).toEqual(["Value over time", "What moved your collection", "By set", "Your cards", "What you paid", "Needs a version"]);
    const chips = container.querySelector('nav[aria-label="Change over time"]') as HTMLElement;
    expect(chips.compareDocumentPosition(container.querySelector("#history") as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows an unpriced card as unpriced, never ¥0", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadCollectionPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    await renderPage();
    const cards = screen.getAllByTestId("collection-card");
    expect(cards).toHaveLength(3);
    const unpriced = cards.find((card) => within(card).queryByText("No price yet"));
    expect(unpriced).toBeDefined();
    expect(unpriced?.textContent).not.toMatch(/¥\s?0(?![\d,])/);
    // Priced cards first, by value.
    expect(within(cards[0]).getByText(/39,600/)).toBeInTheDocument();
  });

  it("says 'No prices yet' when nothing is priced", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadCollectionPage.mockResolvedValueOnce(okPage({ summary: summaryOf({ value_jpy: null, priced_cards: 0, coverage_pct: "0.00" }) }));
    readPrint.mockResolvedValue(null);
    await renderPage();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("No prices yet");
    expect(screen.getByRole("heading", { level: 1 }).textContent).not.toMatch(/¥/);
  });

  it("shows an unavailable window as — with its reason, never 0%", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadCollectionPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    const { container } = await renderPage("30d");
    const chip = container.querySelector('[data-window="30d"]') as HTMLElement;
    expect(chip).toHaveAttribute("aria-current", "page");
    expect(chip).toHaveTextContent("30D—");
    expect(chip).toHaveAttribute("title", "Not enough history yet");
    expect(screen.getByTestId("window-reason")).toHaveTextContent("30D: — Not enough history yet.");
    expect(screen.getByText("— Not enough price history yet")).toBeInTheDocument();
    for (const card of screen.getAllByTestId("collection-card")) expect(card.textContent).not.toMatch(/[+−-]?0(\.0+)?%/);
    expect(container.textContent).not.toMatch(/(^|[^\d.])0\.0%|[+−]0%/);
  });

  it("links the chips to their windows and shows each card's change for the window", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadCollectionPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    const { container } = await renderPage();
    expect(container.querySelector('[data-window="7d"]')).toHaveAttribute("href", "/collection");
    expect(container.querySelector('[data-window="all"]')).toHaveAttribute("href", "/collection?window=all");
    expect(container.querySelector('[data-window="7d"]')).toHaveTextContent("+3.0%");
    const [luffy, shanks] = screen.getAllByTestId("collection-card");
    expect(luffy).toHaveTextContent("+2.5% 7D");
    expect(shanks).toHaveTextContent("−3.0% 7D");
  });

  it("states what you paid with its coverage, in collection words only", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadCollectionPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    const { container } = await renderPage();
    expect(screen.getByText(/You paid/)).toHaveTextContent(/30,000.*for 2 cards.*Priced today.*39,600.*\+32\.0%/);
    expect(screen.getByText(/2 of 5 cards have what you paid/)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/portfolio|P\/L|cost basis|liquidat|hold\/sell|position|ROI/i);
  });

  it("leaves 'What you paid' out when nothing was entered", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    const none = valueFor("7d", true);
    none.paid = { cards_with_paid: 0, cards_compared: 0, total_cards: 5, paid_jpy: null, priced_today_jpy: null, change_pct: null };
    loadCollectionPage.mockResolvedValueOnce(okPage({ values: { "7d": none } }));
    readPrint.mockResolvedValue(null);
    await renderPage();
    expect(screen.queryByRole("heading", { name: "What you paid" })).not.toBeInTheDocument();
  });

  it("lists unresolved entries under 'Needs a version', not in the grid", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadCollectionPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    await renderPage();
    const section = screen.getByRole("heading", { name: "Needs a version" }).closest("section") as HTMLElement;
    expect(within(section).getByText("A card from your old collection")).toBeInTheDocument();
    expect(within(section).getByRole("link", { name: "Find the version" })).toHaveAttribute("href", "/cards");
  });

  it("uses the print's own art when the public read has it", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadCollectionPage.mockResolvedValueOnce(okPage());
    readPrint.mockImplementation(async (id: string) =>
      id === "101"
        ? {
            card_print_id: 101, canonical_card_id: 1, card_code: "OP05-119", name_en: "Monkey.D.Luffy", name_jp: null, rarity: "SEC",
            card_type: "Character", colors: null, language: "ja", treatment: "parallel", release_product_id: 205, release_code: "OP-05",
            release_name: "Awakening of the New Era", release_product_code: "OP-05", official_asset_variant: "p1", artwork_key: null,
            image_url: "https://img.example/101.png", display_image: { url: "https://img.example/101.png", source: "bandai", exact_print_verified: true, owned_asset_selected: true, geometry: null },
            verification_status: "verified", market_index: { index_value_jpy: 19800, source_values: [], source_count: 1, coverage_status: "limited", confidence: "medium" }, siblings: [],
          }
        : null,
    );
    const { container } = await renderPage();
    const img = container.querySelector('img[alt="Monkey.D.Luffy (OP05-119)"]');
    expect(img).not.toBeNull();
    expect(readPrint).toHaveBeenCalledTimes(3);
  });

  it("invites an empty collection to find a card", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadCollectionPage.mockResolvedValueOnce(okPage({ entries: [], summary: summaryOf({ value_jpy: null, priced_cards: 0, total_cards: 0, priced_entries: 0, total_entries: 0, unresolved_entries: 0, coverage_pct: null }) }));
    await renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Your collection is empty" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Find a card" })).toHaveAttribute("href", "/cards");
    expect(readPrint).not.toHaveBeenCalled();
  });

  it("renders the accounts-off and error states plainly", async () => {
    authMock.mockResolvedValue(COLLECTOR);
    loadCollectionPage.mockResolvedValueOnce({ state: "disabled" });
    const { unmount } = await renderPage();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Collections aren’t switched on yet");
    unmount();
    loadCollectionPage.mockResolvedValueOnce({ state: "error" });
    await renderPage();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("We couldn’t load your collection");
  });

  it("asks a visitor to sign in and reads nothing", async () => {
    authMock.mockResolvedValueOnce(null);
    await renderPage();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in?callbackUrl=%2Fcollection");
    expect(loadCollectionPage).not.toHaveBeenCalled();
  });

  it("treats an admin session as not a collector", async () => {
    authMock.mockResolvedValueOnce({ user: { id: "admin", email: "a@example.com" }, sessionKind: "admin" });
    await renderPage();
    expect(loadCollectionPage).not.toHaveBeenCalled();
  });

  it("renders no token into the page", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadCollectionPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    const { container } = await renderPage();
    expect(container.innerHTML).not.toMatch(/Bearer|eyJ|apiToken/);
  });

  it("edits a card in a sheet and refreshes from the API", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadCollectionPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 1 }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await renderPage();

    fireEvent.click(screen.getAllByRole("button", { name: /^Edit Monkey\.D\.Luffy, OP05-119/ })[0]);
    const dialog = screen.getByRole("dialog", { name: "Edit in your collection" });
    const quantity = within(dialog).getByLabelText("How many") as HTMLInputElement;
    expect(quantity.value).toBe("2");
    fireEvent.change(quantity, { target: { value: "3" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledWith("/api/me/collection/1", expect.objectContaining({ method: "PATCH" }));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ quantity: 3, paid_jpy_per_card: 15000, acquired_on: "2026-06-02" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("removes a card only after a second confirm, and Escape closes the sheet", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    loadCollectionPage.mockResolvedValueOnce(okPage());
    readPrint.mockResolvedValue(null);
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await renderPage();

    fireEvent.click(screen.getByRole("button", { name: /^Edit Shanks, OP01-120/ }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Edit Shanks, OP01-120/ }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove from collection" }));
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Yes, remove it" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledWith("/api/me/collection/2", expect.objectContaining({ method: "DELETE" }));
  });
});
