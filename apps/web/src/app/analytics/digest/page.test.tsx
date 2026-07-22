import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AnalyticsDigest, AnalyticsDigestReportListResponse } from "@/lib/api";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
}));

const fetchAnalyticsDigest = vi.fn();
const fetchAnalyticsDigestReports = vi.fn();
const fetchLatestAnalyticsDigest = vi.fn();
const fetchAnalyticsDigestReport = vi.fn();
const triggerGenerateAnalyticsDigest = vi.fn();

const fetchSavedViews = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchSavedViews: (...args: unknown[]) => fetchSavedViews(...args),
    fetchAnalyticsDigest: (...args: unknown[]) => fetchAnalyticsDigest(...args),
    fetchAnalyticsDigestReports: (...args: unknown[]) => fetchAnalyticsDigestReports(...args),
    fetchLatestAnalyticsDigest: (...args: unknown[]) => fetchLatestAnalyticsDigest(...args),
    fetchAnalyticsDigestReport: (...args: unknown[]) => fetchAnalyticsDigestReport(...args),
    triggerGenerateAnalyticsDigest: (...args: unknown[]) => triggerGenerateAnalyticsDigest(...args),
  };
});

import AnalyticsDigestPage from "./page";

const EMPTY_DIGEST: AnalyticsDigest = {
  summary: {
    valuation_mode: "raw_market",
    generated_at: "2026-07-20T10:00:00Z",
    collection_value_jpy: 0,
    graded_adjusted_value_jpy: 0,
    portfolio_risk_score: 0,
    portfolio_risk_level: "low",
    wishlist_target_hits: 0,
    buy_review_count: 0,
    sell_review_count: 0,
    grading_roi_jpy: 0,
    grading_active_count: 0,
    missing_cost_basis_count: 0,
    missing_price_count: 0,
  },
  sections: {
    collection: {
      total_items: 0,
      total_quantity: 0,
      total_cost_basis_jpy: 0,
      raw_market_value_jpy: 0,
      graded_adjusted_value_jpy: 0,
      largest_set_exposure: null,
      largest_rarity_exposure: null,
    },
    wishlist: {
      total_items: 0,
      grail_count: 0,
      high_priority_count: 0,
      target_hit_count: 0,
      total_target_budget_jpy: 0,
      price_coverage_pct: 0,
    },
    buy_decisions: {
      review_buy_count: 0,
      wait_count: 0,
      missing_data_count: 0,
      top_review_buy: [],
    },
    sell_decisions: {
      review_sell_count: 0,
      grade_first_count: 0,
      missing_data_count: 0,
      top_review_sell: [],
    },
    grading: {
      active_submissions: 0,
      received_submissions: 0,
      total_grading_cost_jpy: 0,
      total_graded_value_jpy: 0,
      total_roi_jpy: 0,
      overdue_count: 0,
      best_roi: [],
      worst_roi: [],
    },
    portfolio_risk: {
      risk_score: 0,
      risk_level: "low",
      concentration_score: 0,
      data_quality_score: 0,
      liquidity_proxy_score: 0,
      grading_exposure_score: 0,
      wishlist_overlap_score: 0,
      top_recommendation_flags: [],
    },
  },
  priority_items: {
    top_buy_decisions: [],
    top_sell_decisions: [],
    top_risk_flags: [],
    wishlist_target_hits: [],
    grading_overdue: [],
    missing_data: [],
  },
  deterministic_summary_lines: [
    "Portfolio risk level: low.",
    "No urgent buy, sell, grading, or data quality items to review.",
  ],
};

// A priority item with every optional field null - exercises "render
// cleanly, no literal 'null'/'undefined'" for the priority items lists.
const NULLS_DIGEST: AnalyticsDigest = {
  ...EMPTY_DIGEST,
  priority_items: {
    ...EMPTY_DIGEST.priority_items,
    top_risk_flags: [
      {
        card_id: null,
        card_code: null,
        name_en: null,
        score: null,
        risk_level: null,
        severity: "warning",
        message: "Something to review.",
        link: "/analytics/portfolio-risk",
      },
    ],
  },
};

const EMPTY_HISTORY: AnalyticsDigestReportListResponse = {
  reports: [],
  total: 0,
  limit: 30,
  offset: 0,
  pagination: {
    total: 0,
    limit: 30,
    offset: 0,
    has_next: false,
    has_previous: false,
    next_offset: null,
    previous_offset: null,
  },
};

const HISTORY_WITH_ROWS: AnalyticsDigestReportListResponse = {
  ...EMPTY_HISTORY,
  reports: [
    {
      id: 2,
      created_at: "2026-07-20T09:00:00Z",
      valuation_mode: "raw_market",
      collection_value_jpy: 1000,
      graded_adjusted_value_jpy: null,
      portfolio_risk_score: 10,
      portfolio_risk_level: "low",
      wishlist_target_hits: 1,
      buy_review_count: 2,
      sell_review_count: 0,
      grading_roi_jpy: 0,
    },
    {
      id: 1,
      created_at: "2026-07-19T09:00:00Z",
      valuation_mode: "raw_market",
      collection_value_jpy: null,
      graded_adjusted_value_jpy: null,
      portfolio_risk_score: null,
      portfolio_risk_level: null,
      wishlist_target_hits: 0,
      buy_review_count: 0,
      sell_review_count: 0,
      grading_roi_jpy: null,
    },
  ],
  total: 2,
};

describe("AnalyticsDigestPage", () => {
  beforeEach(() => {
    fetchAnalyticsDigest.mockReset();
    fetchSavedViews.mockReset();
    fetchSavedViews.mockResolvedValue({ items: [], pagination: { total: 0, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null } });
    fetchAnalyticsDigestReports.mockReset();
    fetchLatestAnalyticsDigest.mockReset();
    fetchAnalyticsDigestReport.mockReset();
    triggerGenerateAnalyticsDigest.mockReset();
    fetchAnalyticsDigestReports.mockResolvedValue(EMPTY_HISTORY);
    window.localStorage.clear();
  });

  it("renders an empty digest without crashing", async () => {
    fetchAnalyticsDigest.mockResolvedValue(EMPTY_DIGEST);
    render(<AnalyticsDigestPage />);

    await waitFor(() =>
      expect(screen.getByText("No urgent buy, sell, grading, or data quality items to review.")).toBeInTheDocument(),
    );
    expect(screen.getByText("No stored digests yet.")).toBeInTheDocument();
  });

  it("renders null values cleanly, never as the literal 'null' or 'undefined'", async () => {
    fetchAnalyticsDigest.mockResolvedValue(NULLS_DIGEST);
    fetchAnalyticsDigestReports.mockResolvedValue(HISTORY_WITH_ROWS);
    const { container } = render(<AnalyticsDigestPage />);

    await waitFor(() => expect(screen.getAllByText("not available").length).toBeGreaterThan(0));

    expect(container.textContent).not.toMatch(/\bnull\b/i);
    expect(container.textContent).not.toMatch(/\bundefined\b/i);
  });

  it("refetches with valuation_mode=graded_adjusted when that mode is selected", async () => {
    fetchAnalyticsDigest.mockResolvedValue(EMPTY_DIGEST);
    render(<AnalyticsDigestPage />);

    await waitFor(() =>
      expect(fetchAnalyticsDigest).toHaveBeenCalledWith(
        expect.objectContaining({ valuation_mode: "raw_market" }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Graded adjusted" }));

    await waitFor(() =>
      expect(fetchAnalyticsDigest).toHaveBeenCalledWith(
        expect.objectContaining({ valuation_mode: "graded_adjusted" }),
      ),
    );
  });

  it("switches to fetchLatestAnalyticsDigest when the data source toggle changes", async () => {
    fetchAnalyticsDigest.mockResolvedValue(EMPTY_DIGEST);
    fetchLatestAnalyticsDigest.mockResolvedValue({ id: 1, created_at: "2026-07-20T09:00:00Z", ...EMPTY_DIGEST });
    render(<AnalyticsDigestPage />);

    await waitFor(() => expect(fetchAnalyticsDigest).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Latest stored report" }));

    await waitFor(() =>
      expect(fetchLatestAnalyticsDigest).toHaveBeenCalledWith(
        expect.objectContaining({ valuation_mode: "raw_market" }),
      ),
    );
  });

  it("renders digest history rows", async () => {
    fetchAnalyticsDigest.mockResolvedValue(EMPTY_DIGEST);
    fetchAnalyticsDigestReports.mockResolvedValue(HISTORY_WITH_ROWS);
    render(<AnalyticsDigestPage />);

    await waitFor(() => expect(screen.getAllByText(/View →/).length).toBeGreaterThan(0));
    expect(screen.getAllByText("raw_market").length).toBe(2);
  });

  it("hides the generate action when no admin token is present", async () => {
    fetchAnalyticsDigest.mockResolvedValue(EMPTY_DIGEST);
    render(<AnalyticsDigestPage />);

    await waitFor(() => expect(fetchAnalyticsDigest).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Generate new digest" })).not.toBeInTheDocument();
  });

  it("renders the generate action and calls the admin endpoint when clicked", async () => {
    window.localStorage.setItem("admin_token", "test-token");
    fetchAnalyticsDigest.mockResolvedValue(EMPTY_DIGEST);
    triggerGenerateAnalyticsDigest.mockResolvedValue({
      report_id: 1,
      valuation_mode: "raw_market",
      portfolio_risk_score: 0,
      buy_review_count: 0,
      sell_review_count: 0,
    });
    render(<AnalyticsDigestPage />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Generate new digest" })).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Generate new digest" }));

    await waitFor(() =>
      expect(triggerGenerateAnalyticsDigest).toHaveBeenCalledWith(
        expect.objectContaining({ valuation_mode: "raw_market" }),
      ),
    );
  });
});
