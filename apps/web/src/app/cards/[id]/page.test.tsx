import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Card, CollectionItemList, PriceObservation, WishlistItem } from "@/lib/api";

const useSessionMock = vi.fn(() => ({
  data: null as { user: { email: string; role?: string } } | null,
  status: "unauthenticated",
}));
vi.mock("next-auth/react", () => ({
  useSession: () => useSessionMock(),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
  useParams: () => ({ id: "1" }),
}));

const fetchCard = vi.fn();
const fetchCardPrices = vi.fn();
const fetchCollectorTags = vi.fn();
const fetchCollectionItems = vi.fn();
const fetchWishlistItems = vi.fn();
const fetchCollectionValuation = vi.fn();
const fetchMarketSignalEvents = vi.fn();
const fetchMarketOpportunities = vi.fn();
const fetchCollectorNotes = vi.fn();
const fetchCollectorActivity = vi.fn();
const fetchAdminSourceMappings = vi.fn();
const fetchPrintCatalogue = vi.fn();

vi.mock("@/lib/prints", async () => {
  const actual = await vi.importActual<typeof import("@/lib/prints")>("@/lib/prints");
  return { ...actual, fetchPrintCatalogue: (...args: unknown[]) => fetchPrintCatalogue(...args) };
});

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchCard: (...args: unknown[]) => fetchCard(...args),
    fetchCardPrices: (...args: unknown[]) => fetchCardPrices(...args),
    fetchCollectorTags: (...args: unknown[]) => fetchCollectorTags(...args),
    fetchCollectionItems: (...args: unknown[]) => fetchCollectionItems(...args),
    fetchWishlistItems: (...args: unknown[]) => fetchWishlistItems(...args),
    fetchCollectionValuation: (...args: unknown[]) => fetchCollectionValuation(...args),
    fetchMarketSignalEvents: (...args: unknown[]) => fetchMarketSignalEvents(...args),
    fetchMarketOpportunities: (...args: unknown[]) => fetchMarketOpportunities(...args),
    fetchCollectorNotes: (...args: unknown[]) => fetchCollectorNotes(...args),
    fetchCollectorActivity: (...args: unknown[]) => fetchCollectorActivity(...args),
    fetchAdminSourceMappings: (...args: unknown[]) => fetchAdminSourceMappings(...args),
  };
});

import CardDetailPage from "./page";

const BASE_CARD: Card = {
  id: 1,
  card_code: "OP01-001",
  name_en: "Monkey D. Luffy",
  name_jp: "モンキー・D・ルフィ",
  set_code: "OP01",
  rarity: "L",
  variant: "leader",
  language: "en",
  image_url: null,
  tags: [],
  release_date: null,
  artist: null,
  character: null,
  color: null,
  card_type: null,
  cost: null,
  power: null,
  counter: null,
  attribute: null,
  effect_text: null,
  trigger_text: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const EMPTY_COLLECTION: CollectionItemList = {
  items: [],
  total: 0,
  limit: 100,
  offset: 0,
  pagination: { total: 0, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
};

const EMPTY_WISHLIST: { items: WishlistItem[] } = { items: [] };

const EMPTY_PRICES: PriceObservation[] = [];

function setupDefaultMocks() {
  fetchCard.mockReset();
  fetchCardPrices.mockReset();
  fetchCollectorTags.mockReset();
  fetchCollectionItems.mockReset();
  fetchWishlistItems.mockReset();
  fetchCollectionValuation.mockReset();
  fetchMarketSignalEvents.mockReset();
  fetchMarketOpportunities.mockReset();
  fetchCollectorNotes.mockReset();
  fetchCollectorActivity.mockReset();
  fetchAdminSourceMappings.mockReset();
  useSessionMock.mockReset();

  fetchCard.mockResolvedValue(BASE_CARD);
  fetchCardPrices.mockResolvedValue(EMPTY_PRICES);
  fetchCollectorTags.mockResolvedValue([]);
  fetchCollectionItems.mockResolvedValue(EMPTY_COLLECTION);
  fetchWishlistItems.mockResolvedValue(EMPTY_WISHLIST);
  fetchCollectionValuation.mockResolvedValue({ summary: {}, items: [] });
  fetchMarketSignalEvents.mockResolvedValue({ events: [], summary: {}, limit: 100, offset: 0, pagination: {} });
  fetchMarketOpportunities.mockResolvedValue({ opportunities: [], summary: {}, limit: 100, offset: 0, pagination: {} });
  fetchCollectorNotes.mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0, pagination: {} });
  fetchCollectorActivity.mockResolvedValue({
    events: [],
    summary: { total_events: 0, by_source: {}, by_type: {} },
    limit: 100,
    offset: 0,
    pagination: {},
  });
  fetchAdminSourceMappings.mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0, pagination: {} });
  fetchPrintCatalogue.mockResolvedValue({
    items: [PRINT_BASE, PRINT_PARALLEL],
    total: 2,
    limit: 100,
    offset: 0,
    pagination: {},
    facets: { treatments: [], rarities: [], languages: [], verification_statuses: [] },
  });
  useSessionMock.mockReturnValue({ data: null, status: "unauthenticated" });
}

/** /cards/:id is public, so the DEFAULT session in these tests is anonymous.
 * Any test about the reader's own collection, wishlist, grading, tags or notes
 * must say so explicitly - those panels render only for a real session. */
function signIn(role?: string) {
  useSessionMock.mockReturnValue({
    data: { user: { email: "collector@example.com", ...(role ? { role } : {}) } },
    status: "authenticated",
  });
}

describe("CardDetailPage", () => {
  beforeEach(() => {
    setupDefaultMocks();
  });

  it("renders without crashing when the card has no image, no prices, no collection, and no wishlist", async () => {
    render(<CardDetailPage />);

    // Identity now comes from the canonical print records, which agree with
    // the legacy name in this fixture - so the rendered text is the same, but
    // it settles only after the catalogue request resolves.
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Monkey D. Luffy" })).toBeInTheDocument(),
    );

    // Placeholder image frame shows the card code, not a broken image.
    expect(screen.getAllByText("OP01-001").length).toBeGreaterThan(0);

    // Never a literal "null"/"undefined" anywhere on the page.
    expect(screen.queryByText("null")).not.toBeInTheDocument();
    expect(screen.queryByText("undefined")).not.toBeInTheDocument();
  });

  it("shows the not-owned empty state when there is no collection item", async () => {
    signIn();
    render(<CardDetailPage />);
    await waitFor(() => expect(screen.getByText("Not in collection yet.")).toBeInTheDocument());
  });

  it("shows the not-on-wishlist empty state when there is no wishlist item", async () => {
    signIn();
    render(<CardDetailPage />);
    await waitFor(() => expect(screen.getByText("Not on wishlist.")).toBeInTheDocument());
  });

  it("shows the no-grading-submissions empty state when nothing is graded", async () => {
    signIn();
    render(<CardDetailPage />);
    await waitFor(() => expect(screen.getByText("No grading submissions.")).toBeInTheDocument());
  });

  it("renders owned collection items with price basis labels, never a bare price", async () => {
    signIn();
    fetchCollectionItems.mockResolvedValue({
      ...EMPTY_COLLECTION,
      items: [
        {
          id: 10,
          card_id: 1,
          card_code: "OP01-001",
          name_en: "Monkey D. Luffy",
          name_jp: null,
          set_code: "OP01",
          rarity: "L",
          variant: "leader",
          language: "en",
          quantity: 2,
          condition_label: "NM",
          purchase_price_jpy: 1000,
          purchase_date: null,
          purchase_source: null,
          target_sell_price_jpy: 2000,
          notes: null,
          status: "hold",
          tags: [],
          groups: [],
          grading_submissions: [],
          latest_grading_status: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
      total: 1,
    });

    render(<CardDetailPage />);

    await waitFor(() => expect(screen.getByText("2×")).toBeInTheDocument());
    expect(screen.queryByText("Not in collection yet.")).not.toBeInTheDocument();
  });

  it("no longer renders the card-level price source panel", async () => {
    // Retired deliberately: CardPricePanel showed Yuyu-Tei/SNKRDUNK lines
    // derived from legacy card-level observations, which merge sibling
    // card_print_ids. Pricing now lives only on /prints/[id], where it is
    // exact-print scoped. The component itself still exists in the repo.
    render(<CardDetailPage />);

    // Anchored on public content: "Card tags" is signed-in-only now.
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /Printings of/ })).toBeInTheDocument(),
    );
    expect(screen.queryByText(/Yuyu-Tei sell/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Yuyu-Tei buy/)).not.toBeInTheDocument();
    expect(screen.queryByText(/SNKRDUNK sold/)).not.toBeInTheDocument();
    expect(screen.queryByText(/SNKRDUNK floor/)).not.toBeInTheDocument();
  });

  it("does not render the admin source-mappings panel without a role=admin session", async () => {
    render(<CardDetailPage />);
    // Identity now comes from the canonical print records, which agree with
    // the legacy name in this fixture - so the rendered text is the same, but
    // it settles only after the catalogue request resolves.
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Monkey D. Luffy" })).toBeInTheDocument(),
    );
    expect(screen.queryByText("Source mappings (admin)")).not.toBeInTheDocument();
  });

  it("renders the admin source-mappings panel for a role=admin session", async () => {
    useSessionMock.mockReturnValue({
      data: { user: { email: "admin@example.com", role: "admin" } },
      status: "authenticated",
    });
    render(<CardDetailPage />);
    await waitFor(() => expect(screen.getByText("Source mappings (admin)")).toBeInTheDocument());
  });
});

/** Two printings of BASE_CARD's own card code, shaped as `GET /prints` returns
 * them. Deliberately share name, code and product - the realistic case, and
 * the one that proves the tiles still read as two different collectibles. */
function printItem(id: number, treatment: string, variant: string, indexJpy: number | null) {
  return {
    card_print_id: id,
    canonical_card_id: 42,
    card_code: "OP01-001",
    name_en: "Monkey D. Luffy",
    name_jp: "モンキー・D・ルフィ",
    rarity: "L",
    canonical_rarity: "L",
    card_type: "Leader",
    treatment,
    language: "jp",
    release_product_code: "OP-01",
    original_set_code: "OP-01",
    official_asset_variant: variant,
    image_url: `https://example.test/${id}.png`,
    display_image: null,
    verification_status: "verified",
    market_index: {
      card_print_id: id,
      index_version: 1,
      index_value_jpy: indexJpy,
      calculation_method: "midpoint",
      source_count: indexJpy === null ? 0 : 2,
      coverage_status: indexJpy === null ? "none" : "full",
      confidence: indexJpy === null ? "low" : "high",
      source_values: [],
      auxiliary_values: [],
      freshest_observation_at: null,
      stalest_eligible_source_at: null,
      stale_sources: [],
      calculated_at: "2026-09-01T00:00:00Z",
    },
    source_coverage: [],
    latest_observation_at: null,
  };
}

const PRINT_BASE = printItem(101, "normal", "base", 1200);
const PRINT_PARALLEL = printItem(102, "parallel", "p1", 8400);

describe("CardDetailPage printings", () => {
  beforeEach(() => {
    setupDefaultMocks();
  });

  it("A. no longer renders the legacy card-level price chart", async () => {
    // The chart merged observations across card_print_ids, so a card with
    // several printings was shown one line that belonged to none of them.
    fetchCardPrices.mockResolvedValue([
      {
        id: 1,
        card_id: 1,
        source_id: 1,
        source: "yuyutei",
        observed_at: "2026-08-30T00:00:00Z",
        price_type: "sell",
        price_jpy: 500,
        condition_label: null,
        stock_status: null,
        listing_count: null,
        raw_snapshot_id: null,
      },
      {
        id: 2,
        card_id: 1,
        source_id: 1,
        source: "yuyutei",
        observed_at: "2026-08-31T00:00:00Z",
        price_type: "sell",
        price_jpy: 900,
        condition_label: null,
        stock_status: null,
        listing_count: null,
        raw_snapshot_id: null,
      },
    ] as PriceObservation[]);

    const { container } = render(<CardDetailPage />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Monkey D. Luffy" })).toBeInTheDocument(),
    );

    expect(screen.queryByRole("heading", { name: "Price history" })).not.toBeInTheDocument();
    expect(screen.queryByText("Loading chart…")).not.toBeInTheDocument();
    expect(container.querySelector(".recharts-wrapper")).toBeNull();
    expect(container.querySelector("svg.recharts-surface")).toBeNull();
  });

  it("renders the printings chooser, linking each printing to its own print page", async () => {
    render(<CardDetailPage />);

    await waitFor(() =>
      expect(
        screen.getAllByRole("link").filter((l) => l.getAttribute("href")?.startsWith("/prints/")),
      ).toHaveLength(2),
    );

    const printLinks = screen
      .getAllByRole("link")
      .filter((l) => l.getAttribute("href")?.startsWith("/prints/"));
    expect(printLinks.map((l) => l.getAttribute("href")).sort()).toEqual([
      "/prints/101",
      "/prints/102",
    ]);
  });

  it("queries the catalogue by the card's own code and drops any other card's print", async () => {
    fetchPrintCatalogue.mockResolvedValue({
      items: [PRINT_BASE, { ...PRINT_PARALLEL, card_print_id: 999, card_code: "OP01-0010" }],
      total: 2,
      limit: 100,
      offset: 0,
      pagination: {},
      facets: { treatments: [], rarities: [], languages: [], verification_statuses: [] },
    });

    render(<CardDetailPage />);
    await waitFor(() =>
      expect(
        screen.getAllByRole("link").filter((l) => l.getAttribute("href")?.startsWith("/prints/")),
      ).toHaveLength(1),
    );

    expect(fetchPrintCatalogue).toHaveBeenCalledWith({ q: "OP01-001", limit: 100 });
    // `q` is a substring match server-side; only an exact card_code is this
    // card's printing.
    const hrefs = screen.getAllByRole("link").map((l) => l.getAttribute("href"));
    expect(hrefs).toContain("/prints/101");
    expect(hrefs).not.toContain("/prints/999");
  });

  it("G. keeps collection, wishlist and grading functionality on the page", async () => {
    signIn();
    render(<CardDetailPage />);

    // Each panel resolves on its own request, so wait for the last of them
    // rather than for the Printings heading, which renders immediately.
    await waitFor(() => expect(screen.getByText("Not on wishlist.")).toBeInTheDocument());

    // The page's collector functionality is untouched by this tranche.
    expect(screen.getByRole("heading", { name: /Printings of/ })).toBeInTheDocument();
    expect(screen.getByText("Not in collection yet.")).toBeInTheDocument();
    expect(screen.getByText("No grading submissions.")).toBeInTheDocument();
    expect(screen.getByText("Card tags")).toBeInTheDocument();
  });
});

describe("CardDetailPage canonical identity", () => {
  beforeEach(() => {
    setupDefaultMocks();
  });

  /** The real corruption, verbatim: staging legacy card 1 is card_code
   * OP01-001 named "Monkey D. Luffy", while OP01-001 canonically is Roronoa
   * Zoro. 10 of 25 staging rows are like this. */
  const ZORO_BASE = {
    ...printItem(201, "normal", "base", 500),
    card_code: "OP01-001",
    canonical_card_id: 7,
    name_en: "Roronoa Zoro",
    name_jp: "ロロノア・ゾロ",
  };
  const ZORO_PARALLEL = {
    ...printItem(202, "parallel", "p1", 9000),
    card_code: "OP01-001",
    canonical_card_id: 7,
    name_en: "Roronoa Zoro",
    name_jp: "ロロノア・ゾロ",
  };

  function withCanonical(items: unknown[]) {
    fetchPrintCatalogue.mockResolvedValue({
      items,
      total: items.length,
      limit: 100,
      offset: 0,
      pagination: {},
      facets: { treatments: [], rarities: [], languages: [], verification_statuses: [] },
    });
  }

  it("never labels the printings with the contradicted legacy name", async () => {
    // BASE_CARD is card_code OP01-001 named "Monkey D. Luffy" - the legacy row.
    withCanonical([ZORO_BASE, ZORO_PARALLEL]);

    render(<CardDetailPage />);
    await waitFor(() =>
      expect(
        screen.getAllByRole("link").filter((l) => l.getAttribute("href")?.startsWith("/prints/")),
      ).toHaveLength(2),
    );

    // The canonical name is the page's identity...
    expect(screen.getAllByText(/Roronoa Zoro/).length).toBeGreaterThan(0);
    expect(
      screen.getByRole("heading", { name: /Printings of Roronoa Zoro OP01-001/ }),
    ).toBeInTheDocument();
    // ...and the legacy name appears nowhere, heading included.
    expect(screen.queryByText(/Monkey D\. Luffy/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /Monkey D\. Luffy/ }),
    ).not.toBeInTheDocument();

    // Links stay correct regardless of the name confusion.
    const hrefs = screen.getAllByRole("link").map((l) => l.getAttribute("href"));
    expect(hrefs).toContain("/prints/201");
    expect(hrefs).toContain("/prints/202");
  });

  it("falls back to the card code when canonical records disagree", async () => {
    withCanonical([ZORO_BASE, { ...ZORO_PARALLEL, name_en: "Roronoa Zolo" }]);

    render(<CardDetailPage />);
    await waitFor(() =>
      expect(
        screen.getAllByRole("link").filter((l) => l.getAttribute("href")?.startsWith("/prints/")),
      ).toHaveLength(2),
    );

    const heading = screen.getByRole("heading", { name: /Printings of/ });
    expect(heading).toHaveTextContent("Printings of OP01-001");
    // No arbitrary winner, and still never the legacy name.
    expect(heading).not.toHaveTextContent("Roronoa Zoro");
    expect(heading).not.toHaveTextContent("Roronoa Zolo");
    expect(screen.queryByText(/Monkey D\. Luffy/)).not.toBeInTheDocument();
  });

  it("renders no legacy merged price, observation or card-level index", async () => {
    fetchCardPrices.mockResolvedValue([
      {
        id: 1,
        card_id: 1,
        source_id: 1,
        source: "yuyutei",
        observed_at: "2026-08-31T00:00:00Z",
        price_type: "sell",
        price_jpy: 4321,
        condition_label: null,
        stock_status: null,
        listing_count: null,
        raw_snapshot_id: null,
      },
    ] as PriceObservation[]);
    withCanonical([ZORO_BASE]);

    const { container } = render(<CardDetailPage />);
    await waitFor(() =>
      expect(
        screen.getAllByRole("link").filter((l) => l.getAttribute("href")?.startsWith("/prints/")),
      ).toHaveLength(1),
    );

    // The card-level surfaces are gone outright.
    expect(screen.queryByText("Price observations")).not.toBeInTheDocument();
    expect(screen.queryByText(/Price history/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Yuyu-Tei sell/)).not.toBeInTheDocument();
    expect(screen.queryByText(/SNKRDUNK floor/)).not.toBeInTheDocument();
    expect(container.querySelector("table")).toBeNull();
    // The seeded card-level observation value reaches the DOM nowhere.
    expect(screen.queryByText(/4,321/)).not.toBeInTheDocument();
    // The only ¥ figure is the print's OWN index, on its own tile.
    const yen = (container.textContent ?? "").match(/￥[\d,]+/g) ?? [];
    expect(yen).toEqual(["￥500"]);
  });

  it("keeps collection, wishlist, grading and tags after the pricing removal", async () => {
    signIn();
    withCanonical([ZORO_BASE]);
    render(<CardDetailPage />);

    await waitFor(() => expect(screen.getByText("Not on wishlist.")).toBeInTheDocument());
    expect(screen.getByText("Not in collection yet.")).toBeInTheDocument();
    expect(screen.getByText("No grading submissions.")).toBeInTheDocument();
    expect(screen.getByText("Card tags")).toBeInTheDocument();
  });
});

describe("CardDetailPage hero makes no card-level rarity or variant claim", () => {
  beforeEach(() => {
    setupDefaultMocks();
  });

  /** A real family whose members genuinely disagree: OP04-044 spans a Super
   * Rare base, an Alt Art, a Reprint and an SP Card. Any single chip in the
   * hero would describe at most one of them. */
  const SR_BASE = {
    ...printItem(301, "normal", "base", 80),
    card_code: "OP04-044",
    canonical_card_id: 10,
    name_en: "Kaido",
    name_jp: "カイドウ",
    rarity: "SR",
    canonical_rarity: "SR",
  };
  const SR_ALT_ART = {
    ...printItem(302, "parallel", "p1", 1040),
    card_code: "OP04-044",
    canonical_card_id: 10,
    name_en: "Kaido",
    name_jp: "カイドウ",
    rarity: "SR",
    canonical_rarity: "SR",
  };
  const SP_CARD = {
    ...printItem(303, "parallel", "p2", null),
    card_code: "OP04-044",
    canonical_card_id: 10,
    name_en: "Kaido",
    name_jp: "カイドウ",
    rarity: "SPカード",
    canonical_rarity: "SR",
  };

  async function renderFamily() {
    fetchPrintCatalogue.mockResolvedValue({
      items: [SR_BASE, SR_ALT_ART, SP_CARD],
      total: 3,
      limit: 100,
      offset: 0,
      pagination: {},
      facets: { treatments: [], rarities: [], languages: [], verification_statuses: [] },
    });
    // The legacy row claims a single rarity/variant for the whole family.
    fetchCard.mockResolvedValue({
      ...BASE_CARD,
      card_code: "OP04-044",
      name_en: "Kaido",
      rarity: "SEC",
      variant: "alt_art",
    });

    const utils = render(<CardDetailPage />);
    await waitFor(() =>
      expect(
        screen.getAllByRole("link").filter((l) => l.getAttribute("href")?.startsWith("/prints/")),
      ).toHaveLength(3),
    );
    return utils;
  }

  it("shows the canonical name and card code, and no card-level rarity or variant", async () => {
    await renderFamily();

    const heading = screen.getByRole("heading", { name: "Kaido" });
    expect(heading).toBeInTheDocument();
    expect(screen.getAllByText("OP04-044").length).toBeGreaterThan(0);

    // Scoped to the hero panel specifically: the tiles below legitimately
    // carry rarity and printing chips, and asserting page-wide would either
    // miss the hero or forbid the tiles.
    const hero = heading.closest("div.panel");
    expect(hero).not.toBeNull();
    const heroText = hero?.textContent ?? "";

    // Asserted against what the badges actually RENDER, not the raw tokens:
    // RarityBadge turns "SEC" into "Secret Rare", and VariantBadge prints the
    // variant verbatim - or the word "base" when the variant is null, which is
    // itself a card-level claim this hero must no longer make.
    expect(heroText).not.toMatch(/Secret Rare/);
    expect(heroText).not.toMatch(/SEC\b/);
    expect(heroText).not.toMatch(/alt_art/);
    expect(heroText).not.toMatch(/\bbase\b/);
    // What the hero DOES still say.
    expect(heroText).toContain("Kaido");
    expect(heroText).toContain("OP04-044");
  });

  it("leaves rarity and variant to the individual printing tiles", async () => {
    await renderFamily();

    const links = screen
      .getAllByRole("link")
      .filter((l) => l.getAttribute("href")?.startsWith("/prints/"));

    // Each tile still states its OWN rarity/printing, and the tiles disagree
    // with one another - which is exactly why the hero may not summarise them.
    for (const link of links) {
      expect(within(link).getAllByText("OP04-044").length).toBeGreaterThan(0);
    }
    const labels = links.map((l) => l.getAttribute("aria-label") ?? "");
    expect(new Set(labels).size).toBe(3);
    expect(labels.some((l) => /Alt Art/i.test(l))).toBe(true);
    expect(labels.some((l) => /SP Card/i.test(l))).toBe(true);

    expect(links.map((l) => l.getAttribute("href")).sort()).toEqual([
      "/prints/301",
      "/prints/302",
      "/prints/303",
    ]);
  });
});

describe("CardDetailPage anonymous access", () => {
  beforeEach(() => {
    setupDefaultMocks(); // default session is anonymous
  });

  const ZORO = {
    ...printItem(201, "normal", "base", 500),
    card_code: "OP01-001",
    canonical_card_id: 7,
    name_en: "Roronoa Zoro",
    name_jp: "ロロノア・ゾロ",
  };
  const ZORO_ALT = { ...ZORO, card_print_id: 202, treatment: "parallel", official_asset_variant: "p1" };

  function withPrints(items: unknown[]) {
    fetchPrintCatalogue.mockResolvedValue({
      items,
      total: items.length,
      limit: 100,
      offset: 0,
      pagination: {},
      facets: { treatments: [], rarities: [], languages: [], verification_statuses: [] },
    });
  }

  async function waitForPrintLinks(n: number) {
    await waitFor(() =>
      expect(
        screen.getAllByRole("link").filter((l) => l.getAttribute("href")?.startsWith("/prints/")),
      ).toHaveLength(n),
    );
  }

  it("A. anonymous mismatch case shows canonical identity, never the legacy name", async () => {
    // BASE_CARD is legacy OP01-001 "Monkey D. Luffy"; canonically it is Zoro.
    withPrints([ZORO, ZORO_ALT]);

    render(<CardDetailPage />);
    await waitForPrintLinks(2);

    expect(screen.getByRole("heading", { name: "Roronoa Zoro" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /Printings of Roronoa Zoro OP01-001/ }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Monkey D\. Luffy/)).not.toBeInTheDocument();
  });

  it("B. anonymous multi-print case shows every printing option", async () => {
    withPrints([ZORO, ZORO_ALT, { ...ZORO, card_print_id: 203, official_asset_variant: "p2" }]);

    render(<CardDetailPage />);
    await waitForPrintLinks(3);

    expect(
      screen.getAllByRole("link").map((l) => l.getAttribute("href")).filter((h) => h?.startsWith("/prints/")).sort(),
    ).toEqual(["/prints/201", "/prints/202", "/prints/203"]);
  });

  it("C. anonymous single-print card renders one option normally", async () => {
    withPrints([ZORO]);

    render(<CardDetailPage />);
    await waitForPrintLinks(1);

    expect(screen.getByRole("heading", { name: /Printings of/ })).toBeInTheDocument();
    const link = screen
      .getAllByRole("link")
      .find((l) => l.getAttribute("href")?.startsWith("/prints/"));
    expect(link).toHaveAttribute("href", "/prints/201");
  });

  it("D. exposes no private collection, wishlist, grading, tag or note state", async () => {
    withPrints([ZORO]);

    render(<CardDetailPage />);
    await waitForPrintLinks(1);

    // None of the user-relationship panels render at all - and crucially none
    // of their empty states, which are claims about the reader.
    for (const text of [
      "Not in collection yet.",
      "Not on wishlist.",
      "No grading submissions.",
      "Card tags",
      "Notes",
      "No notes yet.",
      "Failed to load collection status.",
      "Failed to load wishlist status.",
    ]) {
      expect(screen.queryByText(text), text).not.toBeInTheDocument();
    }

    // And no unauthorized request was even attempted.
    expect(fetchCollectionItems).not.toHaveBeenCalled();
    expect(fetchWishlistItems).not.toHaveBeenCalled();
    expect(fetchCollectionValuation).not.toHaveBeenCalled();
    expect(fetchCollectorNotes).not.toHaveBeenCalled();
    expect(fetchCollectorActivity).not.toHaveBeenCalled();
    expect(fetchCollectorTags).not.toHaveBeenCalled();
    expect(fetchAdminSourceMappings).not.toHaveBeenCalled();

    // The public parts of the page are unaffected.
    expect(fetchCard).toHaveBeenCalled();
    expect(fetchPrintCatalogue).toHaveBeenCalledWith({ q: "OP01-001", limit: 100 });
  });

  it("E. a signed-in collector still gets the user-specific panels", async () => {
    signIn();
    withPrints([ZORO]);

    render(<CardDetailPage />);
    await waitFor(() => expect(screen.getByText("Not on wishlist.")).toBeInTheDocument());

    expect(screen.getByText("Not in collection yet.")).toBeInTheDocument();
    expect(screen.getByText("No grading submissions.")).toBeInTheDocument();
    expect(screen.getByText("Card tags")).toBeInTheDocument();
    expect(fetchCollectionItems).toHaveBeenCalled();
    expect(fetchWishlistItems).toHaveBeenCalled();
    // ...and the chooser is still there for them too.
    expect(screen.getByRole("heading", { name: /Printings of/ })).toBeInTheDocument();
  });

  it("F. admin content stays admin-only, anonymous included", async () => {
    withPrints([ZORO]);

    render(<CardDetailPage />);
    await waitForPrintLinks(1);
    expect(screen.queryByText("Source mappings (admin)")).not.toBeInTheDocument();
    expect(fetchAdminSourceMappings).not.toHaveBeenCalled();
  });

  it("F. a signed-in NON-admin collector still sees no admin content", async () => {
    signIn();
    withPrints([ZORO]);

    render(<CardDetailPage />);
    await waitFor(() => expect(screen.getByText("Not on wishlist.")).toBeInTheDocument());
    expect(screen.queryByText("Source mappings (admin)")).not.toBeInTheDocument();
    expect(fetchAdminSourceMappings).not.toHaveBeenCalled();
  });

  it("F. an admin still gets the admin panel", async () => {
    signIn("admin");
    withPrints([ZORO]);

    render(<CardDetailPage />);
    await waitFor(() =>
      expect(screen.getByText("Source mappings (admin)")).toBeInTheDocument(),
    );
    expect(fetchAdminSourceMappings).toHaveBeenCalled();
  });
});
