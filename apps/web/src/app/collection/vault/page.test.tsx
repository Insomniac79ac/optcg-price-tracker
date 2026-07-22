import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Card, CollectionItem } from "@/lib/api";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
}));

const fetchCollectionItems = vi.fn();
const fetchCollectionValuation = vi.fn();
const fetchCards = vi.fn();
const fetchSavedViews = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchCollectionItems: (...args: unknown[]) => fetchCollectionItems(...args),
    fetchCollectionValuation: (...args: unknown[]) => fetchCollectionValuation(...args),
    fetchCards: (...args: unknown[]) => fetchCards(...args),
    fetchSavedViews: (...args: unknown[]) => fetchSavedViews(...args),
  };
});

import CollectionVaultPage from "./page";

function makeItem(overrides: Partial<CollectionItem> = {}): CollectionItem {
  return {
    id: 1,
    card_id: 1,
    card_code: "OP01-001",
    name_en: "Monkey D. Luffy",
    name_jp: null,
    set_code: "OP01",
    rarity: "L",
    variant: "leader",
    language: "en",
    quantity: 1,
    condition_label: "NM",
    purchase_price_jpy: 1000,
    purchase_date: null,
    purchase_source: null,
    target_sell_price_jpy: null,
    notes: null,
    status: "hold",
    tags: [],
    groups: [],
    grading_submissions: [],
    latest_grading_status: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeCard(overrides: Partial<Card> = {}): Card {
  return {
    id: 1,
    card_code: "OP01-001",
    name_en: "Monkey D. Luffy",
    name_jp: null,
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
    ...overrides,
  };
}

const EMPTY_PAGINATION = {
  total: 0,
  limit: 500,
  offset: 0,
  has_next: false,
  has_previous: false,
  next_offset: null,
  previous_offset: null,
};

function itemsResponse(items: CollectionItem[]) {
  return { items, total: items.length, limit: 500, offset: 0, pagination: { ...EMPTY_PAGINATION, total: items.length } };
}

function setupDefaultMocks() {
  fetchCollectionItems.mockReset();
  fetchCollectionValuation.mockReset();
  fetchCards.mockReset();
  fetchSavedViews.mockReset();

  fetchCollectionItems.mockResolvedValue(itemsResponse([]));
  fetchCollectionValuation.mockResolvedValue({ summary: {}, items: [] });
  fetchCards.mockResolvedValue([]);
  fetchSavedViews.mockResolvedValue({ items: [], pagination: EMPTY_PAGINATION });
}

describe("CollectionVaultPage", () => {
  beforeEach(() => {
    setupDefaultMocks();
  });

  it("shows the empty-vault state when the collection has no items", async () => {
    render(<CollectionVaultPage />);
    await waitFor(() =>
      expect(
        screen.getByText("No cards in your vault yet. Add cards to your collection first."),
      ).toBeInTheDocument(),
    );
  });

  it("renders the saved view bar", async () => {
    render(<CollectionVaultPage />);
    await waitFor(() => expect(fetchSavedViews).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Save current view" })).toBeInTheDocument();
  });

  it("renders tiles for owned cards and filters by rarity", async () => {
    fetchCollectionItems.mockResolvedValue(
      itemsResponse([
        makeItem({ id: 1, card_code: "OP01-001", rarity: "L" }),
        makeItem({ id: 2, card_code: "OP01-013", rarity: "SR", name_en: "Roronoa Zoro" }),
      ]),
    );
    fetchCards.mockResolvedValue([makeCard({ id: 1 }), makeCard({ id: 1, card_code: "OP01-013" })]);

    render(<CollectionVaultPage />);
    await waitFor(() => expect(screen.getAllByText("OP01-001").length).toBeGreaterThan(0));
    expect(screen.getAllByText("OP01-013").length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText("Rarity"), { target: { value: "SR" } });

    await waitFor(() => {
      expect(screen.queryAllByText("OP01-001")).toHaveLength(0);
      expect(screen.getAllByText("OP01-013").length).toBeGreaterThan(0);
    });
  });

  it("changes render order when sort changes", async () => {
    fetchCollectionItems.mockResolvedValue(
      itemsResponse([
        makeItem({ id: 1, card_code: "OP01-013", rarity: "SR" }),
        makeItem({ id: 2, card_code: "OP01-001", rarity: "L" }),
      ]),
    );

    render(<CollectionVaultPage />);
    await waitFor(() => expect(screen.getAllByText("OP01-013").length).toBeGreaterThan(0));

    fireEvent.change(screen.getByLabelText("Sort"), { target: { value: "card_code" } });

    await waitFor(() => {
      const codes = screen.getAllByText(/^OP01-/).map((el) => el.textContent);
      const firstIndex = codes.findIndex((c) => c === "OP01-001");
      const secondIndex = codes.findIndex((c) => c === "OP01-013");
      expect(firstIndex).toBeGreaterThanOrEqual(0);
      expect(secondIndex).toBeGreaterThanOrEqual(0);
      expect(firstIndex).toBeLessThan(secondIndex);
    });
  });
});
