import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  MappingQualityItem,
  MappingQualityList,
  RecheckQualityResult,
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

const fetchMappingQuality = vi.fn();
const fetchCards = vi.fn();
const fetchSuggestedCardsForMapping = vi.fn();
const recheckMappingQuality = vi.fn();
const bulkUpdateMappings = vi.fn();
const updateMappingCompatibilityCard = vi.fn();

const fetchSavedViews = vi.fn().mockResolvedValue({
  items: [],
  pagination: { total: 0, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
});
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchSavedViews: (...args: unknown[]) => fetchSavedViews(...args),
    fetchMappingQuality: (...args: unknown[]) => fetchMappingQuality(...args),
    fetchCards: (...args: unknown[]) => fetchCards(...args),
    fetchSuggestedCardsForMapping: (...args: unknown[]) => fetchSuggestedCardsForMapping(...args),
    recheckMappingQuality: (...args: unknown[]) => recheckMappingQuality(...args),
    bulkUpdateMappings: (...args: unknown[]) => bulkUpdateMappings(...args),
    updateMappingCompatibilityCard: (...args: unknown[]) => updateMappingCompatibilityCard(...args),
  };
});

import SourceMappingQualityPage from "./page";

function makeItem(overrides: Partial<MappingQualityItem> = {}): MappingQualityItem {
  return {
    mapping_id: 1,
    identity_classification: "exact",
    confidence_scope: "exact_print",
    source_name: "snkrdunk",
    source_url: "https://snkrdunk.com/x",
    source_card_id: "unrelated-id",
    card_print_id: 101,
    canonical_card_id: 201,
    release_product_id: 301,
    compatibility_card_id: 1,
    compatibility_card_status: "present_valid",
    compatibility_issue_types: [],
    compatibility_match_confidence: 60,
    compatibility_match_confidence_label: "medium",
    exact_confidence_dimensions: {
      card_code: { status: "match", expected: "OP01-001", observed: "OP01-001" },
    },
    canonical_card_code: "OP01-001",
    canonical_name_en: "Monkey D. Luffy",
    canonical_name_jp: "モンキー・D・ルフィ",
    print_language: "jp",
    release_product_code: "OP-01",
    release_product_name: "Romance Dawn",
    official_asset_variant: "base",
    treatment: "normal",
    official_rarity: "L",
    card_id: 1,
    card_code: "OP01-001",
    name_en: "Monkey D. Luffy",
    name_jp: "モンキー・D・ルフィ",
    set_code: "OP01",
    rarity: "L",
    variant: "base",
    is_active: true,
    manual_verified: false,
    review_status: "approved",
    match_confidence: 42,
    match_confidence_label: "low",
    risk_level: "warning",
    issue_types: ["low_confidence"],
    explanation: { positive: [], negative: ["No card code detected"], caps_applied: [] },
    latest_price_observed_at: null,
    last_match_checked_at: null,
    ...overrides,
  };
}

const EMPTY_SUMMARY = {
  total_mappings: 0,
  exact_mapping_count: 0,
  legacy_compatibility_mapping_count: 0,
  broken_mapping_count: 0,
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
};

function listWith(items: MappingQualityItem[]): MappingQualityList {
  return {
    summary: { ...EMPTY_SUMMARY, total_mappings: items.length, warning_count: items.length },
    items,
    pagination: {
      total: items.length,
      limit: 100,
      offset: 0,
      has_next: false,
      has_previous: false,
      next_offset: null,
      previous_offset: null,
    },
  };
}

const EMPTY_LIST: MappingQualityList = {
  summary: EMPTY_SUMMARY,
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
};

describe("SourceMappingQualityPage", () => {
  beforeEach(() => {
    fetchMappingQuality.mockReset();
    fetchCards.mockReset();
    fetchSuggestedCardsForMapping.mockReset();
    recheckMappingQuality.mockReset();
    bulkUpdateMappings.mockReset();
    updateMappingCompatibilityCard.mockReset();
    fetchCards.mockResolvedValue([]);
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("does not crash and shows an empty state when there are no mappings", async () => {
    fetchMappingQuality.mockResolvedValue(EMPTY_LIST);
    render(<SourceMappingQualityPage />);

    await waitFor(() => expect(screen.getByText("No mappings found.")).toBeInTheDocument());
  });

  it("changes the API query when filters change", async () => {
    fetchMappingQuality.mockResolvedValue(EMPTY_LIST);
    render(<SourceMappingQualityPage />);

    await waitFor(() => expect(fetchMappingQuality).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Critical" }));

    await waitFor(() =>
      expect(fetchMappingQuality).toHaveBeenLastCalledWith(
        expect.objectContaining({ risk_level: "critical" }),
      ),
    );
  });

  it("paginates via PaginationControls", async () => {
    const items = Array.from({ length: 3 }, (_, i) => makeItem({ mapping_id: i + 1 }));
    fetchMappingQuality.mockResolvedValue({
      ...listWith(items),
      pagination: {
        total: 250,
        limit: 100,
        offset: 0,
        has_next: true,
        has_previous: false,
        next_offset: 100,
        previous_offset: null,
      },
    });
    render(<SourceMappingQualityPage />);

    await waitFor(() => expect(screen.getAllByText(/OP01-001/).length).toBeGreaterThan(0));

    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() =>
      expect(fetchMappingQuality).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 100 })),
    );
  });

  it("supports row selection via checkboxes", async () => {
    fetchMappingQuality.mockResolvedValue(listWith([makeItem()]));
    render(<SourceMappingQualityPage />);

    await waitFor(() => expect(screen.getAllByText(/OP01-001/).length).toBeGreaterThan(0));

    const checkboxes = screen.getAllByRole("checkbox");
    // First checkbox is "select all", second is the row checkbox.
    fireEvent.click(checkboxes[1]);
    expect((checkboxes[1] as HTMLInputElement).checked).toBe(true);
  });

  it("renders a dry-run preview before a real recheck run", async () => {
    fetchMappingQuality.mockResolvedValue(EMPTY_LIST);
    const result: RecheckQualityResult = {
      dry_run: true,
      summary: { selected: 2, would_update: 2, updated: 0, ok: 0, review: 0, warning: 2, critical: 0 },
      preview: [],
    };
    recheckMappingQuality.mockResolvedValue(result);
    render(<SourceMappingQualityPage />);

    await waitFor(() => expect(fetchMappingQuality).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Bulk tools…" }));
    fireEvent.click(screen.getByRole("button", { name: "Dry run" }));

    await waitFor(() =>
      expect(recheckMappingQuality).toHaveBeenCalledWith(expect.objectContaining({ dry_run: true })),
    );
    await waitFor(() => expect(screen.getByText(/would_update: 2/)).toBeInTheDocument());
    expect(screen.getByText(/dry_run: true/)).toBeInTheDocument();
  });

  it("renders bulk action results after a bulk approve", async () => {
    const item = makeItem();
    fetchMappingQuality.mockResolvedValue(listWith([item]));
    bulkUpdateMappings.mockResolvedValue({
      action: "approve",
      results: [{ mapping_id: item.mapping_id, ok: true, error: null }],
    });
    render(<SourceMappingQualityPage />);

    await waitFor(() => expect(screen.getAllByText(/OP01-001/).length).toBeGreaterThan(0));

    fireEvent.click(screen.getByRole("button", { name: "Bulk tools…" }));
    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[1]);

    // The bulk-tools panel's "Approve" button renders before the per-row
    // quick-action "Approve" button in document order.
    const approveButtons = screen.getAllByRole("button", { name: "Approve" });
    fireEvent.click(approveButtons[0]);

    await waitFor(() =>
      expect(bulkUpdateMappings).toHaveBeenCalledWith([item.mapping_id], "approve", undefined),
    );
    await waitFor(() =>
      expect(
        screen.getAllByText((_content, element) =>
          /approve:\s*1\/1\s*succeeded/.test(element?.textContent ?? ""),
        ).length,
      ).toBeGreaterThan(0),
    );
  });

  it("presents exact-print and optional compatibility identities separately", async () => {
    const item = makeItem({
      card_id: null,
      compatibility_card_id: null,
      compatibility_card_status: "absent",
      card_code: null,
      name_en: null,
      name_jp: null,
      risk_level: "ok",
      issue_types: [],
    });
    fetchMappingQuality.mockResolvedValue(listWith([item]));
    render(<SourceMappingQualityPage />);

    await waitFor(() => expect(screen.getByRole("link", { name: "CardPrint #101" })).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "CardPrint #101" })).toHaveAttribute("href", "/prints/101");
    expect(screen.getByText(/Compatibility card:/).parentElement).toHaveTextContent("Compatibility card: None");
    expect(screen.getByText("Optional metadata; exact pricing identity is valid.")).toBeInTheDocument();
    expect(screen.queryByText(/Missing card/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Replace card/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Change print|Remap print/i })).not.toBeInTheDocument();
  });

  it("labels legacy compatibility confidence as non-authoritative", async () => {
    fetchMappingQuality.mockResolvedValue(listWith([
      makeItem({
        identity_classification: "legacy_compatibility",
        confidence_scope: "compatibility_only",
        card_print_id: null,
        canonical_card_id: null,
        release_product_id: null,
        exact_confidence_dimensions: {},
      }),
    ]));
    render(<SourceMappingQualityPage />);

    await waitFor(() => expect(screen.getAllByText("Legacy compatibility").length).toBeGreaterThan(0));
    expect(screen.getByText("Compatibility-only; not modern exact pricing lineage")).toBeInTheDocument();
    expect(screen.getByText("Compatibility-only confidence")).toBeInTheDocument();
  });

  it("presents broken classification as a separate structural failure", async () => {
    fetchMappingQuality.mockResolvedValue(listWith([
      makeItem({
        identity_classification: "broken",
        confidence_scope: "structural_failure",
        card_print_id: null,
        canonical_card_id: null,
        release_product_id: null,
        compatibility_card_id: null,
        card_id: null,
        compatibility_card_status: "absent",
        match_confidence: null,
        exact_confidence_dimensions: {},
      }),
    ]));
    render(<SourceMappingQualityPage />);

    await waitFor(() => expect(screen.getByText("Broken")).toBeInTheDocument());
    expect(screen.getByText("Structural review required")).toBeInTheDocument();
    expect(screen.getByText("Structural failure — no confidence score")).toBeInTheDocument();
  });

  it("edits exact compatibility metadata with a concise identity-preserving confirmation", async () => {
    const item = makeItem({ compatibility_card_id: null, card_id: null, compatibility_card_status: "absent" });
    fetchMappingQuality.mockResolvedValue(listWith([item]));
    fetchCards.mockResolvedValue([
      {
        id: 2,
        card_code: "OP01-013",
        name_en: "Roronoa Zoro",
        name_jp: null,
        set_code: "OP01",
        rarity: "SR",
        variant: "base",
        language: "jp",
        image_url: null,
        tags: [],
        release_date: null,
        artist: null,
        character: null,
        color: null,
        card_type: null,
        cost: null,
        power: null,
        counter: null,
        attribute: null,
        effect_text: null,
        trigger_text: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ]);
    fetchSuggestedCardsForMapping.mockResolvedValue({
      mapping_id: item.mapping_id,
      identity_classification: "exact",
      authoritative_card_print_id: 101,
      suggestion_scope: "exact_print_review_required",
      message: "Compatibility metadata is optional and cannot change CardPrint identity.",
      matches: [],
    });
    updateMappingCompatibilityCard.mockResolvedValue({
      ...item,
      card_id: 2,
      compatibility_card_id: 2,
      compatibility_card_status: "present_valid",
      operation: "compatibility_card_updated",
      authoritative_card_print_id: 101,
      previous_compatibility_card_id: null,
      new_compatibility_card_id: 2,
      pricing_identity_changed: false,
      deprecated_route: false,
      deprecated_approve_requested: false,
    });
    render(<SourceMappingQualityPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Edit compatibility card" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Edit compatibility card" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Edit compatibility card" })).toBeInTheDocument());
    expect(screen.getByText(/physical print remains unchanged/i)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "None (clear compatibility card)" })).toBeInTheDocument();

    const option = await screen.findByRole("option", { name: /OP01-013/ });
    fireEvent.change(option.parentElement!, { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save compatibility card" }));

    expect(screen.getByRole("heading", { name: "Confirm compatibility-card edit" })).toBeInTheDocument();
    expect(screen.getByText(/authoritative physical-print identity will remain unchanged/i)).toBeInTheDocument();
    const saveButtons = screen.getAllByRole("button", { name: "Save compatibility card" });
    fireEvent.click(saveButtons[saveButtons.length - 1]);

    await waitFor(() => expect(updateMappingCompatibilityCard).toHaveBeenCalledWith(item.mapping_id, 2, undefined));
    await waitFor(() => expect(screen.getByText("pricing_identity_changed=false")).toBeInTheDocument());
    expect(screen.getByText(/Authoritative CardPrint: #101/)).toBeInTheDocument();
    expect(screen.getByText(/Previous compatibility card: None/)).toBeInTheDocument();
    expect(screen.getByText(/New compatibility card: #2/)).toBeInTheDocument();
  });

  it("keeps activate, approve, and review-state controls available", async () => {
    const item = makeItem({ review_status: "needs_review" });
    fetchMappingQuality.mockResolvedValue(listWith([item]));
    bulkUpdateMappings.mockResolvedValue({ action: "activate", results: [{ mapping_id: 1, ok: true, error: null }] });
    render(<SourceMappingQualityPage />);

    await waitFor(() => expect(screen.getByText("needs_review")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Bulk tools…" }));
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    fireEvent.click(screen.getByRole("button", { name: "Activate" }));
    await waitFor(() => expect(bulkUpdateMappings).toHaveBeenCalledWith([1], "activate", undefined));
  });
});
