import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CatalogCoverageGapItem,
  CatalogCoverageGapsResponse,
  CatalogCoverageReport,
} from "@/lib/api";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
}));

const fetchCatalogCoverage = vi.fn();
const fetchCatalogCoverageGaps = vi.fn();

const fetchSavedViews = vi.fn().mockResolvedValue({
  items: [],
  pagination: { total: 0, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
});
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchSavedViews: (...args: unknown[]) => fetchSavedViews(...args),
    fetchCatalogCoverage: (...args: unknown[]) => fetchCatalogCoverage(...args),
    fetchCatalogCoverageGaps: (...args: unknown[]) => fetchCatalogCoverageGaps(...args),
  };
});

import CatalogCoveragePage from "./page";

const LEGACY_SUMMARY = {
  total_cards: 0,
  active_cards: 0,
  inactive_merged_cards: 0,
  sets_count: 0,
  cards_with_yuyutei_mapping: 0,
  cards_with_snkrdunk_mapping: 0,
  cards_without_any_mapping: 0,
  cards_with_recent_yuyutei_price: 0,
  cards_with_recent_snkrdunk_price: 0,
  cards_without_recent_price: 0,
  cards_in_collection: 0,
  cards_on_wishlist: 0,
  cards_with_missing_metadata: 0,
  cards_with_duplicate_risk: 0,
  cards_with_mapping_quality_risk: 0,
  metadata_completion_pct: 0,
  mapping_coverage_pct: 0,
  recent_price_coverage_pct: 0,
};

const EMPTY_REPORT: CatalogCoverageReport = {
  summary: {
    coverage_unit: "eligible_physical_print",
    total_eligible_physical_prints: 12,
    prints_with_any_exact_mapping: 9,
    physical_prints_without_exact_mapping: 3,
    prints_with_any_fresh_source_observation: 7,
    physical_prints_with_exact_mapping_but_no_fresh_observation: 2,
    exact_mapping_coverage_pct: 75,
    fresh_price_coverage_pct: 58.33,
    exact_source_mapping_count: 10,
    legacy_compatibility_mapping_count: 2,
    broken_mapping_count: 1,
    exact_mappings_outside_eligible_prints: 0,
  },
  sources: [{ source_id: 1, source_name: "Yuyu-Tei", eligible_print_count: 12, mapped_print_count: 9, fresh_price_print_count: 7, mapping_coverage_pct: 75, fresh_price_coverage_pct: 58.33 }],
  coverage_by_release_product: [{ key: "op01", label: "OP-01 Romance Dawn", eligible_print_count: 4, mapped_print_count: 3, fresh_price_print_count: 2, mapping_coverage_pct: 75, fresh_price_coverage_pct: 50 }],
  coverage_by_rarity: [],
  coverage_by_language: [],
  mapping_gaps: [],
  price_gaps: [],
  legacy_compatibility: {
    summary: { ...LEGACY_SUMMARY, total_cards: 25, metadata_completion_pct: 96, mapping_coverage_pct: 44, recent_price_coverage_pct: 32 },
    coverage_by_set: [], coverage_by_rarity: [], coverage_by_variant: [], coverage_by_language: [],
    metadata_gaps: [], mapping_gaps: [], price_gaps: [], duplicate_risks: [], mapping_quality_risks: [], price_source_health: null,
  },
  price_source_health: null,
};

function makeGapItem(overrides: Partial<CatalogCoverageGapItem> = {}): CatalogCoverageGapItem {
  return {
    identity_scope: "physical_print",
    card_id: 1,
    compatibility_card_id: 1,
    card_print_id: 101,
    canonical_card_id: 1,
    release_product_id: 11,
    card_code: "OP01-001",
    name_en: "Monkey D. Luffy",
    name_jp: null,
    set_code: "OP01",
    rarity: "L",
    variant: null,
    language: "en",
    release_product_code: "OP-01",
    release_product_name: "Romance Dawn",
    official_asset_variant: null,
    treatment: null,
    exact_mapping_ids: [],
    compatibility_card_ids: [],
    mapped_sources: [],
    fresh_sources: [],
    issue_types: ["missing_artist"],
    severity: "review",
    suggested_action: "update_catalog_metadata",
    ...overrides,
  };
}

function gapsResponse(items: CatalogCoverageGapItem[]): CatalogCoverageGapsResponse {
  return {
    gap_type: "metadata",
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

describe("CatalogCoveragePage", () => {
  beforeEach(() => {
    fetchCatalogCoverage.mockReset();
    fetchCatalogCoverageGaps.mockReset();
  });

  it("does not crash on an empty coverage response and shows empty gap state", async () => {
    fetchCatalogCoverage.mockResolvedValue(EMPTY_REPORT);
    fetchCatalogCoverageGaps.mockResolvedValue(gapsResponse([]));

    render(<CatalogCoveragePage />);

    await waitFor(() => expect(screen.getByText("Eligible physical prints")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("No physical prints without exact source mappings")).toBeInTheDocument());
  });

  it("renders null card fields as 'not available', never as literal null/undefined", async () => {
    fetchCatalogCoverage.mockResolvedValue(EMPTY_REPORT);
    fetchCatalogCoverageGaps.mockResolvedValue(gapsResponse([makeGapItem({ treatment: null, language: null })]));

    render(<CatalogCoveragePage />);

    await waitFor(() => expect(screen.getAllByText("not available").length).toBeGreaterThan(0));
    expect(screen.queryByText("null")).not.toBeInTheDocument();
    expect(screen.queryByText("undefined")).not.toBeInTheDocument();
  });

  it("passes filter changes through to the coverage API call", async () => {
    fetchCatalogCoverage.mockResolvedValue(EMPTY_REPORT);
    fetchCatalogCoverageGaps.mockResolvedValue(gapsResponse([]));

    render(<CatalogCoveragePage />);

    await waitFor(() => expect(fetchCatalogCoverage).toHaveBeenCalled());

    const setCodeInput = screen.getByPlaceholderText("Set code (e.g. OP01)…");
    fireEvent.change(setCodeInput, { target: { value: "OP01" } });

    await waitFor(() =>
      expect(fetchCatalogCoverage).toHaveBeenLastCalledWith(
        expect.objectContaining({ set_code: "OP01" }),
      ),
    );
  });

  it("fetches the selected gap_type when switching tabs", async () => {
    fetchCatalogCoverage.mockResolvedValue(EMPTY_REPORT);
    fetchCatalogCoverageGaps.mockResolvedValue(gapsResponse([]));

    render(<CatalogCoveragePage />);

    await waitFor(() =>
      expect(fetchCatalogCoverageGaps).toHaveBeenCalledWith(
        expect.objectContaining({ gap_type: "mapping" }),
      ),
    );

    screen.getByRole("button", { name: "Compatibility metadata gaps" }).click();

    await waitFor(() =>
      expect(fetchCatalogCoverageGaps).toHaveBeenLastCalledWith(
        expect.objectContaining({ gap_type: "metadata" }),
      ),
    );
  });

  it("uses physical prints as the denominator and renders release-product and source coverage", async () => {
    fetchCatalogCoverage.mockResolvedValue(EMPTY_REPORT);
    fetchCatalogCoverageGaps.mockResolvedValue(gapsResponse([]));
    render(<CatalogCoveragePage />);

    await waitFor(() => expect(screen.getByText("OP-01 Romance Dawn")).toBeInTheDocument());
    expect(screen.getByText("Per-source physical print coverage")).toBeInTheDocument();
    expect(screen.getAllByText("Source mapping coverage").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Fresh price coverage").length).toBeGreaterThan(0);
    expect(screen.queryByText("Coverage by set")).not.toBeInTheDocument();
  });

  it("keeps legacy Card metrics separate from modern pricing coverage", async () => {
    fetchCatalogCoverage.mockResolvedValue(EMPTY_REPORT);
    fetchCatalogCoverageGaps.mockResolvedValue(gapsResponse([]));
    render(<CatalogCoveragePage />);

    await waitFor(() => expect(screen.getByText("Legacy compatibility catalogue metrics")).toBeInTheDocument());
    expect(screen.getByText(/not physical-print pricing coverage/i)).toBeInTheDocument();
    expect(screen.queryByText(/Card Pirate Index coverage/i)).not.toBeInTheDocument();
  });
});
