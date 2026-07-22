import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CollectionAnalytics } from "@/lib/api";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
}));

// jsdom has no ResizeObserver - recharts' ResponsiveContainer needs one, but
// every scenario below keeps the by_set/by_rarity breakdowns empty, so the
// lazy-loaded chart component only ever hits its own "No data available."
// branch and never actually mounts a chart. Stubbed anyway as a safety net.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

const fetchCollectionAnalytics = vi.fn();
const fetchSavedViews = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchSavedViews: (...args: unknown[]) => fetchSavedViews(...args),
    fetchCollectionAnalytics: (...args: unknown[]) => fetchCollectionAnalytics(...args),
  };
});

import CollectionAnalyticsPage from "./page";

const EMPTY_ANALYTICS: CollectionAnalytics = {
  summary: {
    total_items: 0,
    total_quantity: 0,
    total_cost_basis_jpy: 0,
    raw_market_floor_value_jpy: 0,
    graded_adjusted_value_jpy: 0,
    unrealized_pnl_jpy: 0,
    unrealized_pnl_pct: 0,
    items_missing_cost_basis: 0,
    items_missing_market_price: 0,
    owned_unique_cards: 0,
    wishlist_unique_cards: 0,
    grading_active_count: 0,
  },
  breakdowns: {
    by_set: [],
    by_rarity: [],
    by_variant: [],
    by_language: [],
    by_status: [],
    by_tag: [],
    by_group: [],
    by_grading_status: [],
  },
  concentration: {
    top_5_cards_by_value: [],
    top_10_cards_value_pct: 0,
    largest_single_card_value_pct: 0,
    largest_set_exposure: null,
    largest_rarity_exposure: null,
  },
  cost_basis: {
    items_with_cost_basis: 0,
    items_without_cost_basis: 0,
    average_cost_basis_jpy: 0,
    median_cost_basis_jpy: 0,
    highest_cost_basis_items: [],
  },
  valuation_quality: {
    items_with_yuyutei_sell: 0,
    items_with_yuyutei_buy: 0,
    items_with_snkrdunk_floor: 0,
    items_using_graded_value: 0,
    items_using_raw_fallback: 0,
    coverage_pct: 0,
  },
};

// Non-empty (so the full page renders, not just the empty state), but with
// several nullable fields set to null/None to exercise "render cleanly, no
// literal 'null'/'undefined'" - by_set/by_rarity stay empty so the
// recharts-backed chart never mounts (see ResizeObserverStub note above).
const NULLS_ANALYTICS: CollectionAnalytics = {
  ...EMPTY_ANALYTICS,
  summary: { ...EMPTY_ANALYTICS.summary, total_items: 1, total_quantity: 1 },
  breakdowns: {
    ...EMPTY_ANALYTICS.breakdowns,
    by_status: [
      {
        key: "hold",
        label: "hold",
        item_count: 1,
        quantity: 1,
        cost_basis_jpy: 0,
        value_jpy: 0,
        pnl_jpy: 0,
        pnl_pct: null,
        portfolio_weight_pct: 0,
      },
    ],
  },
  cost_basis: {
    ...EMPTY_ANALYTICS.cost_basis,
    items_without_cost_basis: 1,
    highest_cost_basis_items: [
      {
        collection_item_id: 1,
        card_id: 1,
        card_code: "OP01-001",
        name_en: "Test Card",
        name_jp: null,
        purchase_price_jpy: null,
        quantity: 1,
        cost_basis_jpy: 0,
        status: "hold",
      },
    ],
  },
};

describe("CollectionAnalyticsPage", () => {
  beforeEach(() => {
    fetchCollectionAnalytics.mockReset();
    fetchSavedViews.mockReset();
    fetchSavedViews.mockResolvedValue({ items: [], pagination: { total: 0, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null } });
  });

  it("renders an empty analytics response without crashing", async () => {
    fetchCollectionAnalytics.mockResolvedValue(EMPTY_ANALYTICS);
    render(<CollectionAnalyticsPage />);

    await waitFor(() =>
      expect(
        screen.getByText("No collection analytics yet. Add cards to your collection first."),
      ).toBeInTheDocument(),
    );
  });

  it("renders null values cleanly, never as the literal 'null' or 'undefined'", async () => {
    fetchCollectionAnalytics.mockResolvedValue(NULLS_ANALYTICS);
    const { container } = render(<CollectionAnalyticsPage />);

    await waitFor(() => expect(screen.getAllByText("not available").length).toBeGreaterThan(0));

    expect(container.textContent).not.toMatch(/\bnull\b/i);
    expect(container.textContent).not.toMatch(/\bundefined\b/i);
  });

  it("refetches with the new valuation_mode when the toggle changes", async () => {
    fetchCollectionAnalytics.mockResolvedValue(EMPTY_ANALYTICS);
    render(<CollectionAnalyticsPage />);

    await waitFor(() =>
      expect(fetchCollectionAnalytics).toHaveBeenCalledWith({
        valuation_mode: "raw_market",
        include_sold: false,
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Graded adjusted" }));

    await waitFor(() =>
      expect(fetchCollectionAnalytics).toHaveBeenCalledWith({
        valuation_mode: "graded_adjusted",
        include_sold: false,
      }),
    );
  });

  it("refetches with include_sold=true when the checkbox is checked", async () => {
    fetchCollectionAnalytics.mockResolvedValue(EMPTY_ANALYTICS);
    render(<CollectionAnalyticsPage />);

    await waitFor(() =>
      expect(fetchCollectionAnalytics).toHaveBeenCalledWith({
        valuation_mode: "raw_market",
        include_sold: false,
      }),
    );

    fireEvent.click(screen.getByRole("checkbox", { name: "Include sold items" }));

    await waitFor(() =>
      expect(fetchCollectionAnalytics).toHaveBeenCalledWith({
        valuation_mode: "raw_market",
        include_sold: true,
      }),
    );
  });
});
