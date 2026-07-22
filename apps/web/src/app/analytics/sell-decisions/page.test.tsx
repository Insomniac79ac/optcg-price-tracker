import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SellDecisionSupport } from "@/lib/api";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
}));

const fetchSellDecisions = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchSellDecisions: (...args: unknown[]) => fetchSellDecisions(...args),
  };
});

import SellDecisionsPage from "./page";

const EMPTY_RESPONSE: SellDecisionSupport = {
  summary: {
    total_candidates: 0,
    review_sell_count: 0,
    hold_count: 0,
    grade_first_count: 0,
    missing_data_count: 0,
    monitor_count: 0,
    total_potential_sale_value_jpy: 0,
    total_unrealized_pnl_jpy: 0,
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
// candidate that has no pricing/grading/wishlist data at all - exercises
// "render cleanly, no literal 'null'/'undefined'" across every column.
const NULLS_RESPONSE: SellDecisionSupport = {
  ...EMPTY_RESPONSE,
  summary: { ...EMPTY_RESPONSE.summary, total_candidates: 1, missing_data_count: 1 },
  candidates: [
    {
      collection_item_id: 1,
      card_id: 1,
      card_code: "OP01-001",
      name_en: "Test Card",
      name_jp: null,
      set_code: "OP01",
      rarity: "L",
      variant: null,
      language: "en",
      quantity: 1,
      status: "hold",
      condition_label: null,
      score: 0,
      recommended_action: "missing_data",
      current_value_jpy: null,
      current_value_basis: null,
      cost_basis_jpy: null,
      unrealized_pnl_jpy: null,
      unrealized_pnl_pct: null,
      target_sell_price_jpy: null,
      above_target_sell: false,
      latest_prices: { yuyutei_sell: null, yuyutei_buy: null, snkrdunk_floor: null },
      market_context: {
        yuyutei_spread_pct: null,
        snkrdunk_vs_yuyutei_sell_gap_pct: null,
        related_opportunity_score: null,
        related_signal_types: [],
      },
      grading: { has_active_grading: false, latest_status: null, final_grade: null, graded_value_jpy: null },
      wishlist_overlap: { is_on_wishlist: false, priority: null, status: null },
      tags: [],
      groups: [],
      score_reasons: [],
      warnings: ["Missing cost basis", "Missing current value"],
    },
  ],
  pagination: { ...EMPTY_RESPONSE.pagination, total: 1 },
};

const PAGE_1_OF_2: SellDecisionSupport = {
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

describe("SellDecisionsPage", () => {
  beforeEach(() => {
    fetchSellDecisions.mockReset();
  });

  it("renders an empty response without crashing", async () => {
    fetchSellDecisions.mockResolvedValue(EMPTY_RESPONSE);
    render(<SellDecisionsPage />);

    await waitFor(() => expect(screen.getByText("No owned cards to analyze yet.")).toBeInTheDocument());
  });

  it("renders null values cleanly, never as the literal 'null' or 'undefined'", async () => {
    fetchSellDecisions.mockResolvedValue(NULLS_RESPONSE);
    const { container } = render(<SellDecisionsPage />);

    await waitFor(() => expect(screen.getAllByText("not available").length).toBeGreaterThan(0));

    expect(container.textContent).not.toMatch(/\bnull\b/i);
    expect(container.textContent).not.toMatch(/\bundefined\b/i);
  });

  it("refetches with valuation_mode=graded_adjusted when that mode is selected", async () => {
    fetchSellDecisions.mockResolvedValue(EMPTY_RESPONSE);
    render(<SellDecisionsPage />);

    await waitFor(() =>
      expect(fetchSellDecisions).toHaveBeenCalledWith(
        expect.objectContaining({ valuation_mode: "raw_market" }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Graded adjusted" }));

    await waitFor(() =>
      expect(fetchSellDecisions).toHaveBeenCalledWith(
        expect.objectContaining({ valuation_mode: "graded_adjusted" }),
      ),
    );
  });

  it("refetches with the selected action filter", async () => {
    fetchSellDecisions.mockResolvedValue(EMPTY_RESPONSE);
    render(<SellDecisionsPage />);

    await waitFor(() =>
      expect(fetchSellDecisions).toHaveBeenCalledWith(expect.objectContaining({ action: undefined })),
    );

    fireEvent.change(screen.getByLabelText("Action"), { target: { value: "review_sell" } });

    await waitFor(() =>
      expect(fetchSellDecisions).toHaveBeenCalledWith(
        expect.objectContaining({ action: "review_sell" }),
      ),
    );
  });

  it("advances to the next page via pagination controls", async () => {
    fetchSellDecisions.mockResolvedValue(PAGE_1_OF_2);
    render(<SellDecisionsPage />);

    await waitFor(() =>
      expect(fetchSellDecisions).toHaveBeenCalledWith(expect.objectContaining({ offset: 0 })),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Next" }));

    await waitFor(() =>
      expect(fetchSellDecisions).toHaveBeenCalledWith(expect.objectContaining({ offset: 1 })),
    );
  });
});
