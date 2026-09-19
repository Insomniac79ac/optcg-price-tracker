import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PriceGapItem, PriceSourceHealthGapsResponse, PriceSourceHealthReport } from "@/lib/api";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
}));

const fetchPriceSourceHealth = vi.fn();
const fetchPriceSourceHealthGaps = vi.fn();

const fetchSavedViews = vi.fn().mockResolvedValue({
  items: [],
  pagination: { total: 0, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
});
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchSavedViews: (...args: unknown[]) => fetchSavedViews(...args),
    fetchPriceSourceHealth: (...args: unknown[]) => fetchPriceSourceHealth(...args),
    fetchPriceSourceHealthGaps: (...args: unknown[]) => fetchPriceSourceHealthGaps(...args),
  };
});

import PriceSourceHealthPage from "./page";

const EMPTY_SUMMARY = {
  sources_count: 0,
  active_sources_count: 0,
  exact_mapping_count: 0,
  legacy_compatibility_mapping_count: 0,
  broken_mapping_count: 0,
  total_active_mappings: 0,
  mappings_with_recent_price: 0,
  mappings_without_recent_price: 0,
  stale_price_count: 0,
  missing_price_count: 0,
  last_successful_refresh_at: null,
  last_failed_refresh_at: null,
  recent_refresh_success_rate_pct: 0,
  blocked_source_count: 0,
  error_source_count: 0,
};

const EMPTY_REPORT: PriceSourceHealthReport = {
  summary: EMPTY_SUMMARY,
  sources: [],
  coverage_by_release_product: [],
  coverage_by_rarity: [],
  coverage_by_language: [],
  stale_prices: [],
  missing_prices: [],
  legacy_compatibility_mappings: [],
  broken_mappings: [],
  refresh_runs: [],
  warnings: [],
};

function makeGapItem(overrides: Partial<PriceGapItem> = {}): PriceGapItem {
  return {
    mapping_id: 1,
    source_id: 1,
    card_print_id: 101,
    canonical_card_id: 1,
    release_product_id: 11,
    compatibility_card_id: null,
    identity_classification: "exact",
    card_code: "OP01-001",
    name_en: "Monkey D. Luffy",
    name_jp: null,
    release_product_code: "OP-01",
    release_product_name: "Romance Dawn",
    rarity: "L",
    official_asset_variant: null,
    treatment: null,
    language: null,
    source_name: "yuyutei",
    source_url: "https://yuyu-tei.jp/x",
    latest_price_observed_at: null,
    latest_price_type: null,
    latest_price_jpy: null,
    issue_type: "missing_price",
    severity: "warning",
    suggested_action: "run_refresh_or_review_mapping",
    ...overrides,
  };
}

function gapsResponse(items: PriceGapItem[]): PriceSourceHealthGapsResponse {
  return {
    gap_type: "stale",
    items,
    pagination: {
      total: items.length,
      limit: 50,
      offset: 0,
      has_next: false,
      has_previous: false,
      next_offset: null,
      previous_offset: null,
    },
  };
}

describe("PriceSourceHealthPage", () => {
  beforeEach(() => {
    fetchPriceSourceHealth.mockReset();
    fetchPriceSourceHealthGaps.mockReset();
  });

  it("does not crash on an empty response and shows empty gap state", async () => {
    fetchPriceSourceHealth.mockResolvedValue(EMPTY_REPORT);
    fetchPriceSourceHealthGaps.mockResolvedValue(gapsResponse([]));

    render(<PriceSourceHealthPage />);

    await waitFor(() => expect(screen.getByText("Sources")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("No stale prices found")).toBeInTheDocument());
    expect(screen.getByText("No sources found.")).toBeInTheDocument();
  });

  it("renders null card fields as 'not available', never as literal null/undefined", async () => {
    fetchPriceSourceHealth.mockResolvedValue(EMPTY_REPORT);
    fetchPriceSourceHealthGaps.mockResolvedValue(gapsResponse([makeGapItem({ treatment: null })]));

    render(<PriceSourceHealthPage />);

    await waitFor(() => expect(screen.getAllByText("not available").length).toBeGreaterThan(0));
    expect(screen.queryByText("null")).not.toBeInTheDocument();
    expect(screen.queryByText("undefined")).not.toBeInTheDocument();
  });

  it("passes filter changes through to the health API call", async () => {
    fetchPriceSourceHealth.mockResolvedValue(EMPTY_REPORT);
    fetchPriceSourceHealthGaps.mockResolvedValue(gapsResponse([]));

    render(<PriceSourceHealthPage />);

    await waitFor(() => expect(fetchPriceSourceHealth).toHaveBeenCalled());

    const setCodeInput = screen.getByPlaceholderText("Set code (e.g. OP01)…");
    fireEvent.change(setCodeInput, { target: { value: "OP01" } });

    await waitFor(() =>
      expect(fetchPriceSourceHealth).toHaveBeenLastCalledWith(
        expect.objectContaining({ set_code: "OP01" }),
      ),
    );
  });

  it("fetches the selected gap_type when switching tabs", async () => {
    fetchPriceSourceHealth.mockResolvedValue(EMPTY_REPORT);
    fetchPriceSourceHealthGaps.mockResolvedValue(gapsResponse([]));

    render(<PriceSourceHealthPage />);

    await waitFor(() =>
      expect(fetchPriceSourceHealthGaps).toHaveBeenCalledWith(
        expect.objectContaining({ gap_type: "stale" }),
      ),
    );

    screen.getByRole("button", { name: "Missing prices" }).click();

    await waitFor(() =>
      expect(fetchPriceSourceHealthGaps).toHaveBeenLastCalledWith(
        expect.objectContaining({ gap_type: "missing" }),
      ),
    );
  });

  it("shows the SNKRDUNK manual-import note", async () => {
    fetchPriceSourceHealth.mockResolvedValue(EMPTY_REPORT);
    fetchPriceSourceHealthGaps.mockResolvedValue(gapsResponse([]));

    render(<PriceSourceHealthPage />);

    await waitFor(() =>
      expect(
        screen.getByText(/SNKRDUNK automated discovery can be blocked/i),
      ).toBeInTheDocument(),
    );
  });

  it("renders card_id-null exact sibling prints as distinct healthy identities", async () => {
    fetchPriceSourceHealth.mockResolvedValue({
      ...EMPTY_REPORT,
      legacy_compatibility_mappings: [],
      broken_mappings: [],
    });
    fetchPriceSourceHealthGaps.mockResolvedValue(gapsResponse([
      makeGapItem({ mapping_id: 10, card_print_id: 101, compatibility_card_id: null, issue_type: "stale_price" }),
      makeGapItem({ mapping_id: 11, card_print_id: 102, compatibility_card_id: null, issue_type: "missing_price" }),
    ]));
    render(<PriceSourceHealthPage />);

    await waitFor(() => expect(screen.getByText("#101")).toBeInTheDocument());
    expect(screen.getByText("#102")).toBeInTheDocument();
    expect(screen.getAllByText("Exact physical print")).toHaveLength(2);
    expect(screen.getByText("#101").closest("tr")).toHaveTextContent("stale_price");
    expect(screen.getByText("#102").closest("tr")).toHaveTextContent("missing_price");
    expect(screen.queryByText("Missing card")).not.toBeInTheDocument();
  });

  it("labels legacy compatibility and broken mappings separately", async () => {
    fetchPriceSourceHealth.mockResolvedValue({
      ...EMPTY_REPORT,
      summary: { ...EMPTY_SUMMARY, legacy_compatibility_mapping_count: 1, broken_mapping_count: 1 },
      legacy_compatibility_mappings: [makeGapItem({ mapping_id: 20, card_print_id: null, compatibility_card_id: 5, identity_classification: "legacy_compatibility", issue_type: "legacy_compatibility" })],
      broken_mappings: [makeGapItem({ mapping_id: 21, card_print_id: null, identity_classification: "broken", issue_type: "broken_mapping", severity: "critical" })],
    });
    fetchPriceSourceHealthGaps.mockResolvedValue(gapsResponse([]));
    render(<PriceSourceHealthPage />);

    await waitFor(() => expect(screen.getByText("Legacy compatibility only")).toBeInTheDocument());
    expect(screen.getByText("Broken — structural review required")).toBeInTheDocument();
    expect(screen.getByText(/not modern exact pricing lineage/i)).toBeInTheDocument();
    expect(screen.queryByText(/Market Index eligibility/i)).not.toBeInTheDocument();
  });
});
