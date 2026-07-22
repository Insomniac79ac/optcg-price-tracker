import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
}));

const fetchCollectionValuation = vi.fn();
const fetchCards = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchCollectionValuation: (...args: unknown[]) => fetchCollectionValuation(...args),
    fetchCards: (...args: unknown[]) => fetchCards(...args),
  };
});

import { VaultHighlightsSection } from "./VaultHighlightsSection";

describe("VaultHighlightsSection", () => {
  beforeEach(() => {
    fetchCollectionValuation.mockReset();
    fetchCards.mockReset();
  });

  it("renders nothing when the collection is empty", async () => {
    fetchCollectionValuation.mockResolvedValue({ summary: {}, items: [] });
    fetchCards.mockResolvedValue([]);

    const { container } = render(<VaultHighlightsSection />);

    await waitFor(() => expect(fetchCollectionValuation).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the top cards by value when the collection has items", async () => {
    fetchCollectionValuation.mockResolvedValue({
      summary: {},
      items: [
        {
          collection_item_id: 1,
          card_id: 1,
          card_code: "OP01-001",
          name_en: "Monkey D. Luffy",
          name_jp: null,
          set_code: "OP01",
          rarity: "L",
          variant: "leader",
          language: "en",
          quantity: 1,
          condition_label: null,
          purchase_price_jpy: null,
          cost_basis_jpy: null,
          target_sell_price_jpy: null,
          latest_prices: { yuyutei_sell: null, yuyutei_buy: null, snkrdunk_floor: null },
          valuations: {
            retail_value_jpy: null,
            liquidation_value_jpy: null,
            market_floor_value_jpy: 5000,
            pnl_vs_retail_jpy: null,
            pnl_vs_retail_pct: null,
            pnl_vs_liquidation_jpy: null,
            pnl_vs_liquidation_pct: null,
            pnl_vs_market_floor_jpy: null,
            pnl_vs_market_floor_pct: null,
          },
          flags: {
            missing_yuyutei_sell: true,
            missing_yuyutei_buy: true,
            missing_snkrdunk_floor: true,
            missing_cost_basis: true,
            above_target_sell: false,
          },
          tags: [],
          groups: [],
          grading: { has_grading_submission: false, latest_status: null, grading_company: null, final_grade: null, total_grading_cost_jpy: null, graded_value_jpy: null },
          graded_adjusted: { value_jpy: null, basis: null, grading_submission_id: null, grading_company: null, final_grade: null, graded_value_jpy: null, raw_fallback_basis: null, pnl_jpy: null, pnl_pct: null },
        },
      ],
    });
    fetchCards.mockResolvedValue([]);

    render(<VaultHighlightsSection />);

    await waitFor(() => expect(screen.getByText("Vault Highlights")).toBeInTheDocument());
    expect(screen.getAllByText("OP01-001").length).toBeGreaterThan(0);
  });
});
