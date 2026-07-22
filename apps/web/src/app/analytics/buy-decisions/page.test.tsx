import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BuyDecisionSupport } from "@/lib/api";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
}));

const fetchBuyDecisions = vi.fn();
const fetchSavedViews = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchSavedViews: (...args: unknown[]) => fetchSavedViews(...args),
    fetchBuyDecisions: (...args: unknown[]) => fetchBuyDecisions(...args),
  };
});

import BuyDecisionsPage from "./page";

const EMPTY_RESPONSE: BuyDecisionSupport = {
  summary: {
    total_candidates: 0,
    review_buy_count: 0,
    wait_count: 0,
    skip_count: 0,
    missing_data_count: 0,
    monitor_count: 0,
    target_hit_count: 0,
    total_target_budget_jpy: 0,
    total_current_cost_jpy: 0,
    budget_gap_jpy: 0,
    average_score: 0,
  },
  candidates: [],
  limit: 100,
  offset: 0,
  pagination: {
    total: 0,
    limit: 100,
    offset: 0,
    has_next: false,
    has_previous: false,
    next_offset: null,
    previous_offset: null,
  },
};

// Non-empty (so the full page renders, not just the empty state), with a
// candidate that has no pricing/market/wishlist data at all - exercises
// "render cleanly, no literal 'null'/'undefined'" across every column.
const NULLS_RESPONSE: BuyDecisionSupport = {
  ...EMPTY_RESPONSE,
  summary: { ...EMPTY_RESPONSE.summary, total_candidates: 1, missing_data_count: 1 },
  candidates: [
    {
      wishlist_item_id: 1,
      card_id: 1,
      card_code: "OP01-001",
      name_en: "Test Card",
      name_jp: null,
      set_code: "OP01",
      rarity: "L",
      variant: null,
      language: "en",
      score: 0,
      recommended_action: "missing_data",
      priority: "low",
      status: "watching",
      desired_quantity: 1,
      owned_quantity: 0,
      remaining_quantity: 1,
      target_buy_price_jpy: null,
      max_buy_price_jpy: null,
      preferred_condition: null,
      preferred_source: null,
      current_price_jpy: null,
      current_price_source: null,
      target_hit: false,
      gap_to_target_jpy: null,
      gap_to_target_pct: null,
      gap_to_max_jpy: null,
      gap_to_max_pct: null,
      latest_prices: { yuyutei_sell: null, yuyutei_buy: null, snkrdunk_floor: null },
      market_context: {
        snkrdunk_vs_yuyutei_sell_gap_pct: null,
        yuyutei_spread_pct: null,
        related_opportunity_score: null,
        related_signal_types: [],
      },
      tags: [],
      groups: [],
      score_reasons: [],
      warnings: ["Missing current price", "Missing target buy price"],
    },
  ],
  pagination: { ...EMPTY_RESPONSE.pagination, total: 1 },
};

const PAGE_1_OF_2: BuyDecisionSupport = {
  ...NULLS_RESPONSE,
  summary: { ...NULLS_RESPONSE.summary, total_candidates: 2 },
  pagination: {
    total: 2,
    limit: 1,
    offset: 0,
    has_next: true,
    has_previous: false,
    next_offset: 1,
    previous_offset: null,
  },
};

describe("BuyDecisionsPage", () => {
  beforeEach(() => {
    fetchBuyDecisions.mockReset();
    fetchSavedViews.mockReset();
    fetchSavedViews.mockResolvedValue({ items: [], pagination: { total: 0, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null } });
  });

  it("renders an empty response without crashing", async () => {
    fetchBuyDecisions.mockResolvedValue(EMPTY_RESPONSE);
    render(<BuyDecisionsPage />);

    await waitFor(() => expect(screen.getByText("No wishlist cards to analyze yet.")).toBeInTheDocument());
  });

  it("renders null values cleanly, never as the literal 'null' or 'undefined'", async () => {
    fetchBuyDecisions.mockResolvedValue(NULLS_RESPONSE);
    const { container } = render(<BuyDecisionsPage />);

    await waitFor(() => expect(screen.getAllByText("not available").length).toBeGreaterThan(0));

    expect(container.textContent).not.toMatch(/\bnull\b/i);
    expect(container.textContent).not.toMatch(/\bundefined\b/i);
  });

  it("refetches with source_preference=snkrdunk when that option is selected", async () => {
    fetchBuyDecisions.mockResolvedValue(EMPTY_RESPONSE);
    render(<BuyDecisionsPage />);

    await waitFor(() =>
      expect(fetchBuyDecisions).toHaveBeenCalledWith(expect.objectContaining({ source_preference: "auto" })),
    );

    fireEvent.click(screen.getByRole("button", { name: "SNKRDUNK" }));

    await waitFor(() =>
      expect(fetchBuyDecisions).toHaveBeenCalledWith(
        expect.objectContaining({ source_preference: "snkrdunk" }),
      ),
    );
  });

  it("refetches with the selected action filter", async () => {
    fetchBuyDecisions.mockResolvedValue(EMPTY_RESPONSE);
    render(<BuyDecisionsPage />);

    await waitFor(() =>
      expect(fetchBuyDecisions).toHaveBeenCalledWith(expect.objectContaining({ action: undefined })),
    );

    fireEvent.change(screen.getByLabelText("Action"), { target: { value: "review_buy" } });

    await waitFor(() =>
      expect(fetchBuyDecisions).toHaveBeenCalledWith(expect.objectContaining({ action: "review_buy" })),
    );
  });

  it("refetches with the selected priority filter", async () => {
    fetchBuyDecisions.mockResolvedValue(EMPTY_RESPONSE);
    render(<BuyDecisionsPage />);

    await waitFor(() =>
      expect(fetchBuyDecisions).toHaveBeenCalledWith(expect.objectContaining({ priority: undefined })),
    );

    fireEvent.change(screen.getByLabelText("Priority"), { target: { value: "grail" } });

    await waitFor(() =>
      expect(fetchBuyDecisions).toHaveBeenCalledWith(expect.objectContaining({ priority: "grail" })),
    );
  });

  it("advances to the next page via pagination controls", async () => {
    fetchBuyDecisions.mockResolvedValue(PAGE_1_OF_2);
    render(<BuyDecisionsPage />);

    await waitFor(() =>
      expect(fetchBuyDecisions).toHaveBeenCalledWith(expect.objectContaining({ offset: 0 })),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Next" }));

    await waitFor(() =>
      expect(fetchBuyDecisions).toHaveBeenCalledWith(expect.objectContaining({ offset: 1 })),
    );
  });
});
