import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { SystemCheckResponse } from "@/lib/api";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/admin/system-check",
}));

const fetchSystemCheck = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, fetchSystemCheck: (...args: unknown[]) => fetchSystemCheck(...args) };
});

import SystemCheckPage from "./page";

const REPORT: SystemCheckResponse = {
  status: "critical",
  summary: { checks_total: 2, checks_passed: 1, warnings: 0, critical: 1 },
  checks: [
    { name: "exact_mapping_operational_state", status: "fail", severity: "critical", message: "1 active exact mapping targets a non-priceable print." },
    { name: "legacy_compatibility_population", status: "pass", severity: "info", message: "7 legitimate grandfathered mappings retained." },
  ],
  catalog_operations: {
    card_audit_status: "critical", duplicate_risk_count: 0, mapping_quality_critical_count: 1,
    metadata_completion_pct: 98, mapping_coverage_pct: 70, recent_price_coverage_pct: 60,
    price_source_health_status: "warning", latest_import_validation_status: "valid", warnings: [],
    modern_exact_print: {
      mapping_identity: { exact: 38, legacy_compatibility: 7, broken: 1, broken_operational: 1 },
      mapping_operations: { active_exact_mappings: 35, active_exact_to_priceable_print: 34, active_exact_to_non_priceable_print: 1, approved_exact_with_valid_source: 35, operationally_eligible_exact_mappings: 34, exact_mappings_missing_expected_operational_eligibility: 1 },
      observations: { exact: 200, legacy_lineage_less: 4, broken_inconsistent: 0 },
      parents: { card_prints: 50, card_prints_with_canonical_card: 50, card_prints_broken_canonical_card: 0, card_prints_with_release_product: 49, card_prints_without_release_product: 1, card_prints_broken_release_product: 0, active_verified_prints_missing_release_product: 0, market_index_snapshots: 20, market_index_snapshots_with_card_print: 20, market_index_snapshots_broken_card_print: 0 },
    },
    legacy_compatibility: { grandfathered_mappings: 7, mapping_card_references: 12, broken_mapping_card_pointers: 0, collection_items: 9, broken_collection_item_card_pointers: 0, wishlist_items: 4, broken_wishlist_item_card_pointers: 0 },
  },
};

describe("SystemCheckPage exact-print reporting", () => {
  it("separates modern operational and compatibility populations", async () => {
    fetchSystemCheck.mockResolvedValue(REPORT);
    render(<SystemCheckPage />);

    expect(await screen.findByText("Modern exact-print operations")).toBeInTheDocument();
    expect(screen.getByText("Legacy compatibility / informational")).toBeInTheDocument();
    expect(screen.getByText(/not modern exact-pricing failures/i)).toBeInTheDocument();
    expect(screen.getByText("Legacy Card mapping coverage")).toBeInTheDocument();
  });

  it("uses backend severity so grandfathered mappings stay informational", async () => {
    fetchSystemCheck.mockResolvedValue(REPORT);
    render(<SystemCheckPage />);

    const compatibilityRow = (await screen.findByText("legacy_compatibility_population")).closest("tr")!;
    expect(within(compatibilityRow).getByText("pass")).toBeInTheDocument();
    expect(within(compatibilityRow).getByText("info")).toBeInTheDocument();
    const operationalRow = screen.getByText("exact_mapping_operational_state").closest("tr")!;
    expect(within(operationalRow).getByText("fail")).toBeInTheDocument();
    expect(within(operationalRow).getByText("critical")).toBeInTheDocument();
  });
});
