import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CatalogCoverageReport,
  DuplicateList,
  ImportValidationReportListResponse,
  MappingQualityList,
  PriceSourceHealthReport,
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
const fetchPriceSourceHealth = vi.fn();
const fetchMappingQuality = vi.fn();
const fetchCardDuplicates = vi.fn();
const fetchImportValidationReports = vi.fn();
const fetchSavedViews = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchCatalogCoverage: (...args: unknown[]) => fetchCatalogCoverage(...args),
    fetchPriceSourceHealth: (...args: unknown[]) => fetchPriceSourceHealth(...args),
    fetchMappingQuality: (...args: unknown[]) => fetchMappingQuality(...args),
    fetchCardDuplicates: (...args: unknown[]) => fetchCardDuplicates(...args),
    fetchImportValidationReports: (...args: unknown[]) => fetchImportValidationReports(...args),
    fetchSavedViews: (...args: unknown[]) => fetchSavedViews(...args),
  };
});

import CatalogOpsPage from "./page";

const EMPTY_COVERAGE: CatalogCoverageReport = {
  summary: {
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
  },
  coverage_by_set: [],
  coverage_by_rarity: [],
  coverage_by_variant: [],
  coverage_by_language: [],
  metadata_gaps: [],
  mapping_gaps: [],
  price_gaps: [],
  duplicate_risks: [],
  mapping_quality_risks: [],
  price_source_health: null,
};

const EMPTY_HEALTH: PriceSourceHealthReport = {
  summary: {
    sources_count: 0,
    active_sources_count: 0,
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
  },
  sources: [],
  coverage_by_set: [],
  coverage_by_rarity: [],
  stale_prices: [],
  missing_prices: [],
  refresh_runs: [],
  warnings: [],
};

const EMPTY_QUALITY: MappingQualityList = {
  summary: {
    total_mappings: 0,
    ok_count: 0,
    review_count: 0,
    warning_count: 0,
    critical_count: 0,
    low_confidence_count: 0,
    duplicate_source_url_count: 0,
    stale_mapping_count: 0,
    unverified_count: 0,
    inactive_with_recent_price_count: 0,
    active_without_recent_price_count: 0,
  },
  items: [],
  pagination: {
    total: 0,
    limit: 1,
    offset: 0,
    has_next: false,
    has_previous: false,
    next_offset: null,
    previous_offset: null,
  },
};

const EMPTY_DUPLICATES: DuplicateList = {
  summary: {
    total_pairs: 0,
    exact_duplicate_count: 0,
    likely_duplicate_count: 0,
    possible_duplicate_count: 0,
    weak_match_count: 0,
    inactive_merged_cards: 0,
  },
  pairs: [],
  pagination: {
    total: 0,
    limit: 1,
    offset: 0,
    has_next: false,
    has_previous: false,
    next_offset: null,
    previous_offset: null,
  },
};

const EMPTY_REPORTS: ImportValidationReportListResponse = {
  reports: [],
  pagination: {
    total: 0,
    limit: 1,
    offset: 0,
    has_next: false,
    has_previous: false,
    next_offset: null,
    previous_offset: null,
  },
};

describe("CatalogOpsPage", () => {
  beforeEach(() => {
    fetchCatalogCoverage.mockReset();
    fetchPriceSourceHealth.mockReset();
    fetchMappingQuality.mockReset();
    fetchCardDuplicates.mockReset();
    fetchImportValidationReports.mockReset();
    fetchSavedViews.mockReset();
    fetchSavedViews.mockResolvedValue({
      items: [],
      pagination: {
        total: 0,
        limit: 100,
        offset: 0,
        has_next: false,
        has_previous: false,
        next_offset: null,
        previous_offset: null,
      },
    });
  });

  it("does not crash on empty summary data and shows 'not available' for the missing validation status", async () => {
    fetchCatalogCoverage.mockResolvedValue(EMPTY_COVERAGE);
    fetchPriceSourceHealth.mockResolvedValue(EMPTY_HEALTH);
    fetchMappingQuality.mockResolvedValue(EMPTY_QUALITY);
    fetchCardDuplicates.mockResolvedValue(EMPTY_DUPLICATES);
    fetchImportValidationReports.mockResolvedValue(EMPTY_REPORTS);

    render(<CatalogOpsPage />);

    await waitFor(() => expect(screen.getByText("Duplicate risks")).toBeInTheDocument());
    expect(screen.getByText("not available")).toBeInTheDocument();
    expect(screen.queryByText("null")).not.toBeInTheDocument();
    expect(screen.queryByText("undefined")).not.toBeInTheDocument();
  });

  it("links every operations card to its admin page", async () => {
    fetchCatalogCoverage.mockResolvedValue(EMPTY_COVERAGE);
    fetchPriceSourceHealth.mockResolvedValue(EMPTY_HEALTH);
    fetchMappingQuality.mockResolvedValue(EMPTY_QUALITY);
    fetchCardDuplicates.mockResolvedValue(EMPTY_DUPLICATES);
    fetchImportValidationReports.mockResolvedValue(EMPTY_REPORTS);

    render(<CatalogOpsPage />);

    await waitFor(() => expect(screen.getByText("Card Catalog")).toBeInTheDocument());

    const expectedLinks: [string, string][] = [
      ["Card Catalog", "/admin/cards"],
      ["Import Validation", "/admin/import-validation"],
      ["Card Audit", "/admin/card-audit"],
      ["Duplicate Review", "/admin/card-duplicates"],
      ["Source Candidate Matching", "/admin/snkrdunk-candidates"],
      ["Source Mapping Quality", "/admin/source-mapping-quality"],
      ["Catalog Coverage", "/admin/catalog-coverage"],
      ["Price Source Health", "/admin/price-source-health"],
      ["System Check", "/admin/system-check"],
    ];

    // Scoped to the operations-card grid specifically (data-testid) - the
    // sidebar nav and the page's own QuickActionBar now also link to
    // several of these same admin pages with the same link text (Source
    // Mapping Quality, Catalog Coverage, Price Source Health), so a query
    // scoped only to <main> would match more than one element.
    const grid = within(screen.getByTestId("catalog-ops-links"));
    for (const [title, href] of expectedLinks) {
      const link = grid.getByText(title).closest("a");
      expect(link).toHaveAttribute("href", href);
    }
  });

  it("shows an error state when every summary fetch fails without throwing", async () => {
    fetchCatalogCoverage.mockRejectedValue(new Error("boom"));
    fetchPriceSourceHealth.mockRejectedValue(new Error("boom"));
    fetchMappingQuality.mockRejectedValue(new Error("boom"));
    fetchCardDuplicates.mockRejectedValue(new Error("boom"));
    fetchImportValidationReports.mockRejectedValue(new Error("boom"));

    render(<CatalogOpsPage />);

    await waitFor(() =>
      expect(screen.getByText(/Failed to load the catalog operations summary/)).toBeInTheDocument(),
    );
  });
});
