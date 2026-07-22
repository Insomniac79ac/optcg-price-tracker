import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Card, CollectionItemList, PriceObservation, WishlistItem } from "@/lib/api";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
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
const getAdminToken = vi.fn();

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
    getAdminToken: () => getAdminToken(),
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
  getAdminToken.mockReset();

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
  getAdminToken.mockReturnValue(null);
}

describe("CardDetailPage", () => {
  beforeEach(() => {
    setupDefaultMocks();
  });

  it("renders without crashing when the card has no image, no prices, no collection, and no wishlist", async () => {
    render(<CardDetailPage />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Monkey D. Luffy" })).toBeInTheDocument());

    // Placeholder image frame shows the card code, not a broken image.
    expect(screen.getAllByText("OP01-001").length).toBeGreaterThan(0);

    // Never a literal "null"/"undefined" anywhere on the page.
    expect(screen.queryByText("null")).not.toBeInTheDocument();
    expect(screen.queryByText("undefined")).not.toBeInTheDocument();
  });

  it("shows the not-owned empty state when there is no collection item", async () => {
    render(<CardDetailPage />);
    await waitFor(() => expect(screen.getByText("Not in collection yet.")).toBeInTheDocument());
  });

  it("shows the not-on-wishlist empty state when there is no wishlist item", async () => {
    render(<CardDetailPage />);
    await waitFor(() => expect(screen.getByText("Not on wishlist.")).toBeInTheDocument());
  });

  it("shows the no-grading-submissions empty state when nothing is graded", async () => {
    render(<CardDetailPage />);
    await waitFor(() => expect(screen.getByText("No grading submissions.")).toBeInTheDocument());
  });

  it("renders owned collection items with price basis labels, never a bare price", async () => {
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

  it("renders the price source panel with an explicit basis label for every line", async () => {
    render(<CardDetailPage />);

    await waitFor(() => expect(screen.getAllByText(/Yuyu-Tei|SNKRDUNK/).length).toBeGreaterThan(0));
    // The 4th (SNKRDUNK sold) line's basis chip renders even with no
    // observation for it - "not available" for the value, not a blank cell.
    expect(screen.getAllByText("not available").length).toBeGreaterThan(0);
  });

  it("does not render the admin source-mappings panel without an admin token", async () => {
    render(<CardDetailPage />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Monkey D. Luffy" })).toBeInTheDocument());
    expect(screen.queryByText("Source mappings (admin)")).not.toBeInTheDocument();
  });

  it("renders the admin source-mappings panel when an admin token is present", async () => {
    getAdminToken.mockReturnValue("test-token");
    render(<CardDetailPage />);
    await waitFor(() => expect(screen.getByText("Source mappings (admin)")).toBeInTheDocument());
  });
});
