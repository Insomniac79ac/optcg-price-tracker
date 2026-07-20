import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PortfolioRisk } from "@/lib/api";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

const fetchPortfolioRisk = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchPortfolioRisk: (...args: unknown[]) => fetchPortfolioRisk(...args),
  };
});

import PortfolioRiskPage from "./page";

const EMPTY_RESPONSE: PortfolioRisk = {
  summary: {
    risk_score: 0,
    risk_level: "low",
    total_value_jpy: 0,
    total_cost_basis_jpy: 0,
    largest_single_card_weight_pct: 0,
    top_5_weight_pct: 0,
    top_10_weight_pct: 0,
    largest_set_weight_pct: 0,
    largest_rarity_weight_pct: 0,
    missing_price_count: 0,
    missing_cost_basis_count: 0,
    stale_price_count: 0,
    wide_spread_count: 0,
    active_grading_count: 0,
    wishlist_overlap_count: 0,
  },
  risk_breakdown: {
    concentration: { score: 0, level: "low", warnings: [], top_cards: [], top_sets: [], top_rarities: [] },
    data_quality: {
      score: 0, level: "low", warnings: [], missing_prices: [], missing_cost_basis: [], stale_prices: [],
    },
    liquidity_proxy: { score: 0, level: "low", warnings: [], wide_spread_cards: [], low_listing_cards: [] },
    grading_exposure: {
      score: 0, level: "low", warnings: [], active_grading_items: [], high_cost_pending_items: [],
    },
    wishlist_overlap: { score: 0, level: "low", warnings: [], owned_wishlist_items: [] },
  },
  exposures: { by_set: [], by_rarity: [], by_variant: [], by_language: [], by_tag: [], by_group: [] },
  recommendation_flags: [],
};

// Non-empty response with cards that have no pricing/grading/wishlist data
// at all - exercises "render cleanly, no literal 'null'/'undefined'" across
// every table this page renders.
const NULLS_RESPONSE: PortfolioRisk = {
  ...EMPTY_RESPONSE,
  summary: { ...EMPTY_RESPONSE.summary, missing_price_count: 1, stale_price_count: 1 },
  risk_breakdown: {
    ...EMPTY_RESPONSE.risk_breakdown,
    concentration: {
      score: 10,
      level: "medium",
      warnings: ["Largest single card is 42% of portfolio value."],
      top_cards: [
        {
          card_id: 1,
          collection_item_id: 1,
          card_code: "OP01-001",
          name_en: null,
          set_code: "OP01",
          rarity: "L",
          quantity: 1,
          value_jpy: null,
          portfolio_weight_pct: null,
          cost_basis_jpy: null,
          warnings: [],
        },
      ],
      top_sets: [],
      top_rarities: [],
    },
    data_quality: {
      score: 10,
      level: "medium",
      warnings: [],
      missing_prices: [
        {
          card_id: 2,
          collection_item_id: 2,
          card_code: "OP01-002",
          name_en: null,
          set_code: "OP01",
          rarity: "R",
          quantity: 1,
          value_jpy: null,
          portfolio_weight_pct: null,
          cost_basis_jpy: null,
          warnings: [],
          issue: "No current market price available",
          latest_observed_at: null,
          suggested_action: "fix_missing_prices",
        },
      ],
      missing_cost_basis: [],
      stale_prices: [],
    },
    grading_exposure: {
      score: 5,
      level: "low",
      warnings: [],
      active_grading_items: [
        {
          card_id: 3,
          collection_item_id: 3,
          card_code: "OP01-003",
          name_en: null,
          set_code: "OP01",
          rarity: "SR",
          quantity: 1,
          value_jpy: null,
          portfolio_weight_pct: null,
          cost_basis_jpy: null,
          warnings: [],
          grading_company: null,
          submission_status: "planned",
          grading_cost_jpy: null,
          expected_return_date: null,
          overdue: false,
        },
      ],
      high_cost_pending_items: [],
    },
  },
  recommendation_flags: [
    {
      flag_type: "missing_prices",
      severity: "warning",
      message: "1 owned item(s) have no current market price.",
      related_cards: [],
      suggested_action: "fix_missing_prices",
    },
  ],
};

describe("PortfolioRiskPage", () => {
  beforeEach(() => {
    fetchPortfolioRisk.mockReset();
  });

  it("renders an empty response without crashing", async () => {
    fetchPortfolioRisk.mockResolvedValue(EMPTY_RESPONSE);
    render(<PortfolioRiskPage />);

    await waitFor(() => expect(screen.getAllByText("0").length).toBeGreaterThan(0));
    expect(screen.getByText("No risk flags triggered.")).toBeInTheDocument();
  });

  it("renders null values cleanly, never as the literal 'null' or 'undefined'", async () => {
    fetchPortfolioRisk.mockResolvedValue(NULLS_RESPONSE);
    const { container } = render(<PortfolioRiskPage />);

    await waitFor(() => expect(screen.getAllByText("not available").length).toBeGreaterThan(0));

    expect(container.textContent).not.toMatch(/\bnull\b/i);
    expect(container.textContent).not.toMatch(/\bundefined\b/i);
  });

  it("refetches with valuation_mode=graded_adjusted when that mode is selected", async () => {
    fetchPortfolioRisk.mockResolvedValue(EMPTY_RESPONSE);
    render(<PortfolioRiskPage />);

    await waitFor(() =>
      expect(fetchPortfolioRisk).toHaveBeenCalledWith(
        expect.objectContaining({ valuation_mode: "raw_market" }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Graded adjusted" }));

    await waitFor(() =>
      expect(fetchPortfolioRisk).toHaveBeenCalledWith(
        expect.objectContaining({ valuation_mode: "graded_adjusted" }),
      ),
    );
  });

  it("refetches with include_sold=true when the checkbox is toggled", async () => {
    fetchPortfolioRisk.mockResolvedValue(EMPTY_RESPONSE);
    render(<PortfolioRiskPage />);

    await waitFor(() =>
      expect(fetchPortfolioRisk).toHaveBeenCalledWith(expect.objectContaining({ include_sold: false })),
    );

    fireEvent.click(screen.getByLabelText("Include sold"));

    await waitFor(() =>
      expect(fetchPortfolioRisk).toHaveBeenCalledWith(expect.objectContaining({ include_sold: true })),
    );
  });
});
