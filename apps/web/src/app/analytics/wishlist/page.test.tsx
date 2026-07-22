import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WishlistAnalytics } from "@/lib/api";

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
// every scenario below keeps the by_priority/by_status breakdowns empty, so
// the lazy-loaded chart component only ever hits its own "No data
// available." branch and never actually mounts a chart. Stubbed anyway as a
// safety net.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

const fetchWishlistAnalytics = vi.fn();
const fetchSavedViews = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchSavedViews: (...args: unknown[]) => fetchSavedViews(...args),
    fetchWishlistAnalytics: (...args: unknown[]) => fetchWishlistAnalytics(...args),
  };
});

import WishlistAnalyticsPage from "./page";

const EMPTY_ANALYTICS: WishlistAnalytics = {
  summary: {
    total_items: 0,
    watching_count: 0,
    target_hit_count: 0,
    purchased_count: 0,
    passed_count: 0,
    grail_count: 0,
    high_priority_count: 0,
    owned_already_count: 0,
    total_target_budget_jpy: 0,
    total_max_budget_jpy: 0,
    total_current_price_jpy: 0,
    budget_gap_to_target_jpy: 0,
    budget_gap_to_max_jpy: 0,
    average_target_price_jpy: 0,
    median_target_price_jpy: 0,
  },
  breakdowns: {
    by_priority: [],
    by_status: [],
    by_set: [],
    by_rarity: [],
    by_preferred_source: [],
    by_preferred_condition: [],
  },
  target_hits: [],
  budget_plan: {
    grail_targets: [],
    high_priority_targets: [],
    best_gap_to_target: [],
    largest_budget_items: [],
    already_owned: [],
  },
  price_coverage: {
    items_with_current_price: 0,
    items_missing_current_price: 0,
    coverage_pct: 0,
  },
};

// Non-empty (so the full page renders, not just the empty state), with a
// grail target that has no pricing data at all - exercises "render cleanly,
// no literal 'null'/'undefined'" across the target table's price/gap/source
// columns. by_priority/by_status stay empty so the recharts-backed chart
// never mounts (see ResizeObserverStub note above).
const NULLS_ANALYTICS: WishlistAnalytics = {
  ...EMPTY_ANALYTICS,
  summary: { ...EMPTY_ANALYTICS.summary, total_items: 1 },
  budget_plan: {
    ...EMPTY_ANALYTICS.budget_plan,
    grail_targets: [
      {
        wishlist_item_id: 1,
        card_id: 1,
        card_code: "OP01-001",
        name_en: "Test Card",
        name_jp: null,
        set_code: "OP01",
        rarity: "L",
        priority: "grail",
        status: "watching",
        desired_quantity: 1,
        owned_quantity: 0,
        target_buy_price_jpy: null,
        max_buy_price_jpy: null,
        preferred_current_price_jpy: null,
        preferred_current_price_source: null,
        target_hit: false,
        gap_to_target_jpy: null,
        gap_to_target_pct: null,
      },
    ],
  },
};

describe("WishlistAnalyticsPage", () => {
  beforeEach(() => {
    fetchWishlistAnalytics.mockReset();
    fetchSavedViews.mockReset();
    fetchSavedViews.mockResolvedValue({ items: [], pagination: { total: 0, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null } });
  });

  it("renders an empty analytics response without crashing", async () => {
    fetchWishlistAnalytics.mockResolvedValue(EMPTY_ANALYTICS);
    render(<WishlistAnalyticsPage />);

    await waitFor(() =>
      expect(
        screen.getByText("No wishlist analytics yet. Add cards to your wishlist first."),
      ).toBeInTheDocument(),
    );
  });

  it("renders null values cleanly, never as the literal 'null' or 'undefined'", async () => {
    fetchWishlistAnalytics.mockResolvedValue(NULLS_ANALYTICS);
    const { container } = render(<WishlistAnalyticsPage />);

    await waitFor(() => expect(screen.getAllByText("not available").length).toBeGreaterThan(0));

    expect(container.textContent).not.toMatch(/\bnull\b/i);
    expect(container.textContent).not.toMatch(/\bundefined\b/i);
  });

  it("refetches with include_removed=true when the checkbox is checked", async () => {
    fetchWishlistAnalytics.mockResolvedValue(EMPTY_ANALYTICS);
    render(<WishlistAnalyticsPage />);

    await waitFor(() =>
      expect(fetchWishlistAnalytics).toHaveBeenCalledWith({
        include_removed: false,
        include_purchased: false,
      }),
    );

    fireEvent.click(screen.getByRole("checkbox", { name: "Include removed" }));

    await waitFor(() =>
      expect(fetchWishlistAnalytics).toHaveBeenCalledWith({
        include_removed: true,
        include_purchased: false,
      }),
    );
  });

  it("refetches with include_purchased=true when the checkbox is checked", async () => {
    fetchWishlistAnalytics.mockResolvedValue(EMPTY_ANALYTICS);
    render(<WishlistAnalyticsPage />);

    await waitFor(() =>
      expect(fetchWishlistAnalytics).toHaveBeenCalledWith({
        include_removed: false,
        include_purchased: false,
      }),
    );

    fireEvent.click(screen.getByRole("checkbox", { name: "Include purchased" }));

    await waitFor(() =>
      expect(fetchWishlistAnalytics).toHaveBeenCalledWith({
        include_removed: false,
        include_purchased: true,
      }),
    );
  });
});
