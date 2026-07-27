import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CardMergePreview, CardMergeResult, DuplicateList, DuplicatePair } from "@/lib/api";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
}));

const fetchCardDuplicates = vi.fn();
const bulkPreviewCardDuplicates = vi.fn();
const fetchCardMergePreview = vi.fn();
const mergeCards = vi.fn();

const fetchSavedViews = vi.fn().mockResolvedValue({
  items: [],
  pagination: { total: 0, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
});
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchSavedViews: (...args: unknown[]) => fetchSavedViews(...args),
    fetchCardDuplicates: (...args: unknown[]) => fetchCardDuplicates(...args),
    bulkPreviewCardDuplicates: (...args: unknown[]) => bulkPreviewCardDuplicates(...args),
    fetchCardMergePreview: (...args: unknown[]) => fetchCardMergePreview(...args),
    mergeCards: (...args: unknown[]) => mergeCards(...args),
  };
});

import CardDuplicatesPage from "./page";

function makeCard(overrides: Partial<DuplicatePair["source_card"]> = {}) {
  return {
    id: 1,
    card_code: "OP01-001",
    name_en: "Monkey D. Luffy",
    name_jp: null,
    set_code: "OP01",
    rarity: "L",
    variant: "leader",
    language: "en",
    is_active: true,
    merged_into_card_id: null,
    ...overrides,
  };
}

function makePair(overrides: Partial<DuplicatePair> = {}): DuplicatePair {
  return {
    source_card: makeCard({ id: 2, rarity: "SR" }),
    target_card: makeCard({ id: 1 }),
    score: 92,
    confidence_label: "exact_duplicate",
    explanation: { positive: ["exact card_code match"], negative: [], caps_applied: [] },
    recommended_target_card_id: 1,
    warnings: [],
    ...overrides,
  };
}

const EMPTY_SUMMARY = {
  total_pairs: 0,
  exact_duplicate_count: 0,
  likely_duplicate_count: 0,
  possible_duplicate_count: 0,
  weak_match_count: 0,
  inactive_merged_cards: 0,
};

const EMPTY_LIST: DuplicateList = {
  summary: EMPTY_SUMMARY,
  pairs: [],
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

function listWith(pairs: DuplicatePair[]): DuplicateList {
  return {
    summary: { ...EMPTY_SUMMARY, total_pairs: pairs.length, exact_duplicate_count: pairs.length },
    pairs,
    pagination: {
      total: pairs.length,
      limit: 100,
      offset: 0,
      has_next: false,
      has_previous: false,
      next_offset: null,
      previous_offset: null,
    },
  };
}

function makePreview(overrides: Partial<CardMergePreview> = {}): CardMergePreview {
  return {
    source_card: makeCard({ id: 2, rarity: "SR" }),
    target_card: makeCard({ id: 1 }),
    duplicate_score: 92,
    confidence_label: "exact_duplicate",
    explanation: { positive: ["exact card_code match"], negative: [], caps_applied: [] },
    field_merge_preview: {},
    affected_records: { source_card_mappings: 1, collection_items: 2, wishlist_items: 0 },
    warnings: [],
    ...overrides,
  };
}

describe("CardDuplicatesPage", () => {
  beforeEach(() => {
    fetchCardDuplicates.mockReset();
    bulkPreviewCardDuplicates.mockReset();
    fetchCardMergePreview.mockReset();
    mergeCards.mockReset();
  });

  it("does not crash and shows an empty state when there are no duplicates", async () => {
    fetchCardDuplicates.mockResolvedValue(EMPTY_LIST);
    render(<CardDuplicatesPage />);

    await waitFor(() => expect(screen.getByText("No duplicate pairs found.")).toBeInTheDocument());
  });

  it("changes the API query when filters change", async () => {
    fetchCardDuplicates.mockResolvedValue(EMPTY_LIST);
    render(<CardDuplicatesPage />);

    await waitFor(() => expect(fetchCardDuplicates).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText("Set code"), { target: { value: "OP01" } });

    await waitFor(() =>
      expect(fetchCardDuplicates).toHaveBeenLastCalledWith(
        expect.objectContaining({ set_code: "OP01" }),
      ),
    );
  });

  it("paginates via PaginationControls", async () => {
    fetchCardDuplicates.mockResolvedValue({
      ...listWith([makePair()]),
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
    render(<CardDuplicatesPage />);

    await waitFor(() => expect(screen.getAllByText(/OP01-001/).length).toBeGreaterThan(0));

    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() =>
      expect(fetchCardDuplicates).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 100 })),
    );
  });

  it("renders affected records in the merge preview modal", async () => {
    fetchCardDuplicates.mockResolvedValue(listWith([makePair()]));
    fetchCardMergePreview.mockResolvedValue(makePreview());
    render(<CardDuplicatesPage />);

    await waitFor(() => expect(screen.getAllByText(/OP01-001/).length).toBeGreaterThan(0));

    fireEvent.click(screen.getByRole("button", { name: "Preview merge" }));

    await waitFor(() => expect(screen.getByText(/collection_items:/)).toBeInTheDocument());
  });

  it("renders the dry-run merge result", async () => {
    fetchCardDuplicates.mockResolvedValue(listWith([makePair()]));
    fetchCardMergePreview.mockResolvedValue(makePreview());
    const result: CardMergeResult = {
      dry_run: true,
      merged: false,
      source_card_id: 2,
      target_card_id: 1,
      affected_records: {},
      field_changes: {},
      warnings: [],
      duplicate_score: 92,
      confidence_label: "exact_duplicate",
    };
    mergeCards.mockResolvedValue(result);
    render(<CardDuplicatesPage />);

    await waitFor(() => expect(screen.getAllByText(/OP01-001/).length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: "Preview merge" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Dry-run merge" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Dry-run merge" }));

    await waitFor(() => expect(screen.getByText("dry_run: true")).toBeInTheDocument());
  });

  it("requires typing MERGE before execute merge is enabled", async () => {
    fetchCardDuplicates.mockResolvedValue(listWith([makePair()]));
    fetchCardMergePreview.mockResolvedValue(makePreview());
    render(<CardDuplicatesPage />);

    await waitFor(() => expect(screen.getAllByText(/OP01-001/).length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: "Preview merge" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Execute merge" })).toBeDisabled());

    fireEvent.change(screen.getByPlaceholderText("Type MERGE to confirm"), {
      target: { value: "MERGE" },
    });

    await waitFor(() => expect(screen.getByRole("button", { name: "Execute merge" })).not.toBeDisabled());
    expect(mergeCards).not.toHaveBeenCalled();
  });

  it("renders bulk preview results", async () => {
    fetchCardDuplicates.mockResolvedValue(EMPTY_LIST);
    bulkPreviewCardDuplicates.mockResolvedValue({ previews: [makePreview()] });
    render(<CardDuplicatesPage />);

    await waitFor(() => expect(fetchCardDuplicates).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Bulk preview" }));

    await waitFor(() => expect(bulkPreviewCardDuplicates).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText(/score 92/)).toBeInTheDocument());
  });
});
