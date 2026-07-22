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

const EMPTY_SUMMARY = {
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
  summary: EMPTY_SUMMARY,
  coverage_by_set: [],
  coverage_by_rarity: [],
  coverage_by_variant: [],
  coverage_by_language: [],
  metadata_gaps: [],
  mapping_gaps: [],
  price_gaps: [],
  duplicate_risks: [],
  mapping_quality_risks: [],
};

function makeGapItem(overrides: Partial<CatalogCoverageGapItem> = {}): CatalogCoverageGapItem {
  return {
    card_id: 1,
    card_code: "OP01-001",
    name_en: "Monkey D. Luffy",
    name_jp: null,
    set_code: "OP01",
    rarity: "L",
    variant: null,
    language: "en",
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

    await waitFor(() => expect(screen.getByText("Total cards")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("No metadata gaps found")).toBeInTheDocument());
  });

  it("renders null card fields as 'not available', never as literal null/undefined", async () => {
    fetchCatalogCoverage.mockResolvedValue(EMPTY_REPORT);
    fetchCatalogCoverageGaps.mockResolvedValue(
      gapsResponse([makeGapItem({ variant: null, language: null })]),
    );

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
        expect.objectContaining({ gap_type: "metadata" }),
      ),
    );

    screen.getByRole("button", { name: "Mapping gaps" }).click();

    await waitFor(() =>
      expect(fetchCatalogCoverageGaps).toHaveBeenLastCalledWith(
        expect.objectContaining({ gap_type: "mapping" }),
      ),
    );
  });
});
