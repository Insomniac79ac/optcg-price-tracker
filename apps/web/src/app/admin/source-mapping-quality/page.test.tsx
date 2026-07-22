import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  MappingQualityItem,
  MappingQualityList,
  RecheckQualityResult,
  SuggestedCardsForMapping,
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
const replaceMappingCard = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchMappingQuality: (...args: unknown[]) => fetchMappingQuality(...args),
    fetchCards: (...args: unknown[]) => fetchCards(...args),
    fetchSuggestedCardsForMapping: (...args: unknown[]) => fetchSuggestedCardsForMapping(...args),
    recheckMappingQuality: (...args: unknown[]) => recheckMappingQuality(...args),
    bulkUpdateMappings: (...args: unknown[]) => bulkUpdateMappings(...args),
    replaceMappingCard: (...args: unknown[]) => replaceMappingCard(...args),
  };
});

import SourceMappingQualityPage from "./page";

function makeItem(overrides: Partial<MappingQualityItem> = {}): MappingQualityItem {
  return {
    mapping_id: 1,
    source_name: "snkrdunk",
    source_url: "https://snkrdunk.com/x",
    source_card_id: "unrelated-id",
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
    replaceMappingCard.mockReset();
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

    await waitFor(() => expect(screen.getByText(/OP01-001/)).toBeInTheDocument());

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

    await waitFor(() => expect(screen.getByText(/OP01-001/)).toBeInTheDocument());

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

  it("opens the suggested cards modal and renders ranked matches", async () => {
    const item = makeItem();
    fetchMappingQuality.mockResolvedValue(listWith([item]));
    const matches: SuggestedCardsForMapping = {
      mapping_id: item.mapping_id,
      matches: [
        {
          card_id: 1,
          card_code: "OP01-001",
          name_en: "Monkey D. Luffy",
          name_jp: "モンキー・D・ルフィ",
          set_code: "OP01",
          rarity: "L",
          variant: "base",
          score: 60,
          confidence_label: "medium",
          ambiguous: false,
          explanation: { positive: ["exact card_code match"], negative: [], caps_applied: [] },
        },
      ],
    };
    fetchSuggestedCardsForMapping.mockResolvedValue(matches);
    render(<SourceMappingQualityPage />);

    await waitFor(() => expect(screen.getByText(/OP01-001/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Suggested cards" }));

    await waitFor(() => expect(fetchSuggestedCardsForMapping).toHaveBeenCalledWith(item.mapping_id));
    await waitFor(() => expect(screen.getByText(/exact card_code match/)).toBeInTheDocument());
  });

  it("replaces the mapped card from the suggested cards modal", async () => {
    const item = makeItem();
    fetchMappingQuality.mockResolvedValue(listWith([item]));
    fetchSuggestedCardsForMapping.mockResolvedValue({
      mapping_id: item.mapping_id,
      matches: [
        {
          card_id: 2,
          card_code: "OP01-013",
          name_en: "Roronoa Zoro",
          name_jp: "ロロノア・ゾロ",
          set_code: "OP01",
          rarity: "SR",
          variant: "base",
          score: 90,
          confidence_label: "exact",
          ambiguous: false,
          explanation: { positive: ["exact card_code match"], negative: [], caps_applied: [] },
        },
      ],
    });
    replaceMappingCard.mockResolvedValue({ ...item, card_id: 2, card_code: "OP01-013" });
    render(<SourceMappingQualityPage />);

    await waitFor(() => expect(screen.getByText(/OP01-001/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Suggested cards" }));
    await waitFor(() => expect(screen.getByText(/OP01-013/)).toBeInTheDocument());

    const replaceApproveButtons = screen.getAllByRole("button", { name: "Replace & approve" });
    // The first one belongs to the ranked-match row (card_id=2); the second
    // is the always-rendered manual "replace with a different card" picker.
    fireEvent.click(replaceApproveButtons[0]);

    await waitFor(() =>
      expect(replaceMappingCard).toHaveBeenCalledWith(item.mapping_id, 2, undefined, true),
    );
  });
});
