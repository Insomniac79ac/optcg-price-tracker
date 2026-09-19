import { render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CardAuditReport } from "@/lib/api";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/admin/card-audit",
}));

const fetchCardAudit = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, fetchCardAudit: (...args: unknown[]) => fetchCardAudit(...args) };
});

import CardAuditPage from "./page";

const REPORT: CardAuditReport = {
  summary: { total_cards: 40, total_issues: 1, critical_issues: 1, warning_issues: 0 },
  catalog_coverage: null,
  modern_exact_print_audit: {
    eligible_physical_prints: 50,
    exact_mappings: 38,
    active_exact_mappings: 35,
    mappings_with_fresh_observations: 30,
    mappings_without_fresh_observations: 5,
    active_exact_mappings_non_priceable: 1,
    broken_mappings: 0,
  },
  compatibility_audit: {
    grandfathered_legacy_mappings: 7,
    legacy_card_references: 12,
    broken_compatibility_card_pointers: 0,
    collection_items_card_keyed: 9,
    collection_items_broken_card_references: 0,
    wishlist_items_card_keyed: 4,
    wishlist_items_broken_card_references: 0,
  },
  issues: [{
    issue_type: "active_exact_mapping_non_priceable",
    severity: "critical",
    card_ids: [],
    card_code: "OP01-001",
    message: "An active exact mapping targets a non-priceable physical print.",
    suggested_action: "Review the physical print operational state.",
    details: { card_print_ids: [101] },
  }],
};

describe("CardAuditPage exact-print reporting", () => {
  it("renders modern exact-print and legacy compatibility audits separately", async () => {
    fetchCardAudit.mockResolvedValue(REPORT);
    render(<CardAuditPage />);

    const modern = await screen.findByRole("heading", { name: "Modern exact-print audit" });
    const modernSection = modern.closest("section")!;
    expect(within(modernSection).getByText("Eligible physical prints")).toBeInTheDocument();
    expect(within(modernSection).getByText("Active mappings to non-priceable prints")).toBeInTheDocument();

    const compatibility = screen.getByRole("heading", { name: "Legacy compatibility audit" });
    const compatibilitySection = compatibility.closest("section")!;
    expect(within(compatibilitySection).getByText("Grandfathered legacy mappings")).toBeInTheDocument();
    expect(within(compatibilitySection).getByText(/informational, not exact-pricing failures/i)).toBeInTheDocument();
  });

  it("presents non-priceable exact mapping issues with CardPrint identity", async () => {
    fetchCardAudit.mockResolvedValue(REPORT);
    render(<CardAuditPage />);

    await waitFor(() => expect(screen.getAllByText("active_exact_mapping_non_priceable").length).toBeGreaterThan(0));
    expect(screen.getByRole("link", { name: "CardPrint #101" })).toHaveAttribute("href", "/prints/101");
    expect(screen.getByText("critical")).toBeInTheDocument();
  });
});
