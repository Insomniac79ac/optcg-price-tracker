import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GradingAnalytics } from "@/lib/api";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

const fetchGradingAnalytics = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchGradingAnalytics: (...args: unknown[]) => fetchGradingAnalytics(...args),
  };
});

import GradingAnalyticsPage from "./page";

const EMPTY_RESPONSE: GradingAnalytics = {
  summary: {
    total_submissions: 0,
    active_submissions: 0,
    received_submissions: 0,
    cancelled_submissions: 0,
    total_declared_value_jpy: 0,
    total_grading_cost_jpy: 0,
    total_graded_value_jpy: 0,
    total_raw_cost_basis_jpy: 0,
    total_roi_jpy: 0,
    total_roi_pct: null,
    average_grade: null,
    median_grade: null,
    profitable_count: 0,
    unprofitable_count: 0,
    missing_graded_value_count: 0,
    missing_cost_basis_count: 0,
    items_waiting_return: 0,
  },
  breakdowns: { by_status: [], by_company: [], by_grade: [], by_set: [], by_rarity: [] },
  roi: {
    best_roi_submissions: [],
    worst_roi_submissions: [],
    highest_graded_value: [],
    highest_grading_cost: [],
    missing_value_or_cost: [],
  },
  pending: { waiting_return: [], overdue: [], expected_next_30d: [] },
  submissions: [],
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
// submission that has no pricing/tracking/notes data at all - exercises
// "render cleanly, no literal 'null'/'undefined'" across every column.
const NULLS_SUBMISSION = {
  grading_submission_id: 1,
  collection_item_id: 1,
  card_id: 1,
  card_code: "OP01-001",
  name_en: "Test Card",
  name_jp: null,
  set_code: "OP01",
  rarity: "L",
  variant: null,
  quantity: 1,
  grading_company: "PSA",
  submission_name: null,
  submission_status: "planned",
  declared_value_jpy: null,
  grading_fee_jpy: null,
  shipping_fee_jpy: null,
  insurance_fee_jpy: null,
  other_fee_jpy: null,
  total_cost_jpy: 0,
  purchase_price_jpy: null,
  raw_cost_basis_jpy: null,
  graded_value_jpy: null,
  roi_jpy: null,
  roi_pct: null,
  submitted_at: null,
  expected_return_date: null,
  received_at: null,
  days_in_grading: null,
  final_grade: null,
  cert_number: null,
  tracking_number: null,
  notes: null,
  tags: [],
  groups: [],
  flags: {
    profitable: false,
    missing_cost_basis: true,
    missing_graded_value: true,
    overdue: false,
    active: true,
  },
};

const NULLS_RESPONSE: GradingAnalytics = {
  ...EMPTY_RESPONSE,
  summary: { ...EMPTY_RESPONSE.summary, total_submissions: 1, missing_graded_value_count: 1 },
  roi: { ...EMPTY_RESPONSE.roi, missing_value_or_cost: [NULLS_SUBMISSION] },
  submissions: [NULLS_SUBMISSION],
  pagination: { ...EMPTY_RESPONSE.pagination, total: 1 },
};

const PAGE_1_OF_2: GradingAnalytics = {
  ...NULLS_RESPONSE,
  summary: { ...NULLS_RESPONSE.summary, total_submissions: 2 },
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

describe("GradingAnalyticsPage", () => {
  beforeEach(() => {
    fetchGradingAnalytics.mockReset();
  });

  it("renders an empty response without crashing", async () => {
    fetchGradingAnalytics.mockResolvedValue(EMPTY_RESPONSE);
    render(<GradingAnalyticsPage />);

    await waitFor(() =>
      expect(screen.getByText("No grading submissions to analyze yet.")).toBeInTheDocument(),
    );
  });

  it("renders null values cleanly, never as the literal 'null' or 'undefined'", async () => {
    fetchGradingAnalytics.mockResolvedValue(NULLS_RESPONSE);
    const { container } = render(<GradingAnalyticsPage />);

    await waitFor(() => expect(screen.getAllByText("not available").length).toBeGreaterThan(0));

    expect(container.textContent).not.toMatch(/\bnull\b/i);
    expect(container.textContent).not.toMatch(/\bundefined\b/i);
  });

  it("refetches with include_cancelled=true when the checkbox is checked", async () => {
    fetchGradingAnalytics.mockResolvedValue(EMPTY_RESPONSE);
    render(<GradingAnalyticsPage />);

    await waitFor(() =>
      expect(fetchGradingAnalytics).toHaveBeenCalledWith(
        expect.objectContaining({ include_cancelled: false }),
      ),
    );

    fireEvent.click(screen.getByRole("checkbox", { name: "Include cancelled" }));

    await waitFor(() =>
      expect(fetchGradingAnalytics).toHaveBeenCalledWith(
        expect.objectContaining({ include_cancelled: true }),
      ),
    );
  });

  it("refetches with the selected company/status filters", async () => {
    fetchGradingAnalytics.mockResolvedValue(EMPTY_RESPONSE);
    render(<GradingAnalyticsPage />);

    await waitFor(() =>
      expect(fetchGradingAnalytics).toHaveBeenCalledWith(
        expect.objectContaining({ grading_company: undefined, status: undefined }),
      ),
    );

    fireEvent.change(screen.getByLabelText("Company"), { target: { value: "PSA" } });

    await waitFor(() =>
      expect(fetchGradingAnalytics).toHaveBeenCalledWith(expect.objectContaining({ grading_company: "PSA" })),
    );

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "received" } });

    await waitFor(() =>
      expect(fetchGradingAnalytics).toHaveBeenCalledWith(expect.objectContaining({ status: "received" })),
    );
  });

  it("advances to the next page via pagination controls", async () => {
    fetchGradingAnalytics.mockResolvedValue(PAGE_1_OF_2);
    render(<GradingAnalyticsPage />);

    await waitFor(() =>
      expect(fetchGradingAnalytics).toHaveBeenCalledWith(expect.objectContaining({ offset: 0 })),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Next" }));

    await waitFor(() =>
      expect(fetchGradingAnalytics).toHaveBeenCalledWith(expect.objectContaining({ offset: 1 })),
    );
  });
});
