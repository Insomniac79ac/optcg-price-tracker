import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CandidateMatches,
  RematchAllResult,
  SnkrdunkCandidate,
  SnkrdunkCandidateList,
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

const fetchSnkrdunkCandidates = vi.fn();
const fetchCards = vi.fn();
const fetchCandidateMatches = vi.fn();
const rematchCandidate = vi.fn();
const rematchAllCandidates = vi.fn();
const approveCandidateMatch = vi.fn();
const rejectCandidateMatch = vi.fn();
const fetchCandidatePrintOptions = vi.fn();

const fetchSavedViews = vi.fn().mockResolvedValue({
  items: [],
  pagination: { total: 0, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
});
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchSavedViews: (...args: unknown[]) => fetchSavedViews(...args),
    fetchSnkrdunkCandidates: (...args: unknown[]) => fetchSnkrdunkCandidates(...args),
    fetchCards: (...args: unknown[]) => fetchCards(...args),
    fetchCandidateMatches: (...args: unknown[]) => fetchCandidateMatches(...args),
    rematchCandidate: (...args: unknown[]) => rematchCandidate(...args),
    rematchAllCandidates: (...args: unknown[]) => rematchAllCandidates(...args),
    approveCandidateMatch: (...args: unknown[]) => approveCandidateMatch(...args),
    rejectCandidateMatch: (...args: unknown[]) => rejectCandidateMatch(...args),
    fetchCandidatePrintOptions: (...args: unknown[]) => fetchCandidatePrintOptions(...args),
  };
});

import SnkrdunkCandidatesPage from "./page";

function makeCandidate(overrides: Partial<SnkrdunkCandidate> = {}): SnkrdunkCandidate {
  return {
    id: 1,
    discovery_run_id: null,
    source_url: "https://snkrdunk.com/trading-cards/op01-001-luffy-l",
    title: "OP01-001 モンキー・D・ルフィ L",
    price_jpy: 1500,
    image_url: null,
    listing_count: 3,
    condition_label: "near_mint",
    raw_text: null,
    normalized_title: "OP01-001 モンキー・D・ルフィ L",
    detected_card_code: "OP01-001",
    detected_set_code: "OP01",
    detected_rarity: "L",
    detected_variant: null,
    match_status: "suggested",
    matched_card_id: null,
    match_confidence: null,
    best_match_card_id: 1,
    best_match_score: 93,
    best_match_confidence_label: "exact",
    created_at: "2026-07-20T09:00:00Z",
    updated_at: "2026-07-20T09:00:00Z",
    matched_card: null,
    ...overrides,
  };
}

const EMPTY_LIST: SnkrdunkCandidateList = {
  items: [],
  total: 0,
  limit: 200,
  offset: 0,
  pagination: {
    total: 0,
    limit: 200,
    offset: 0,
    has_next: false,
    has_previous: false,
    next_offset: null,
    previous_offset: null,
  },
};

function listWith(items: SnkrdunkCandidate[]): SnkrdunkCandidateList {
  return { ...EMPTY_LIST, items, total: items.length };
}

describe("SnkrdunkCandidatesPage", () => {
  beforeEach(() => {
    fetchSnkrdunkCandidates.mockReset();
    fetchCards.mockReset();
    fetchCandidateMatches.mockReset();
    rematchCandidate.mockReset();
    rematchAllCandidates.mockReset();
    approveCandidateMatch.mockReset();
    rejectCandidateMatch.mockReset();
    fetchCandidatePrintOptions.mockReset();
    fetchCards.mockResolvedValue([]);
    // Opening the detail panel always asks for the printings; tests that do
    // not care about them still need a promise back rather than undefined.
    fetchCandidatePrintOptions.mockResolvedValue({
      candidate: {
        candidate_id: 1,
        source: "snkrdunk",
        title: null,
        source_url: "https://snkrdunk.com/cards/1",
        source_image_url: null,
        detected_card_code: "OP01-001",
        detected_set_code: null,
        detected_variant: null,
        detected_rarity: null,
        price_jpy: null,
      },
      options: [],
      resolvable_card_print_id: null,
      ambiguity_reason: null,
    });
  });

  it("does not crash and shows an empty state when there are no candidates", async () => {
    fetchSnkrdunkCandidates.mockResolvedValue(EMPTY_LIST);
    render(<SnkrdunkCandidatesPage />);

    await waitFor(() =>
      expect(screen.getByText("No candidates found.")).toBeInTheDocument(),
    );
  });

  it("renders match score/status for a candidate row", async () => {
    fetchSnkrdunkCandidates.mockResolvedValue(listWith([makeCandidate()]));
    render(<SnkrdunkCandidatesPage />);

    await waitFor(() =>
      expect(screen.getAllByText(/OP01-001/).length).toBeGreaterThan(0),
    );
    expect(screen.getByText("93")).toBeInTheDocument();
    expect(screen.getAllByText("exact").length).toBeGreaterThan(0);
    expect(screen.getByText("suggested")).toBeInTheDocument();
  });

  it("opens the match detail modal and renders ranked matches", async () => {
    const candidate = makeCandidate();
    fetchSnkrdunkCandidates.mockResolvedValue(listWith([candidate]));
    const matches: CandidateMatches = {
      candidate,
      matches: [
        {
          card_id: 1,
          card_code: "OP01-001",
          name_en: "Monkey D. Luffy",
          name_jp: "モンキー・D・ルフィ",
          set_code: "OP01",
          rarity: "L",
          variant: "base",
          score: 93,
          confidence_label: "exact",
          ambiguous: false,
          explanation: {
            positive: ["exact card_code match"],
            negative: [],
            caps_applied: [],
          },
        },
      ],
    };
    fetchCandidateMatches.mockResolvedValue(matches);
    render(<SnkrdunkCandidatesPage />);

    await waitFor(() => expect(screen.getAllByText(/OP01-001/).length).toBeGreaterThan(0));

    fireEvent.click(screen.getByRole("button", { name: "Matches" }));

    await waitFor(() => expect(fetchCandidateMatches).toHaveBeenCalledWith(1));
    await waitFor(() =>
      expect(screen.getByText(/exact card_code match/)).toBeInTheDocument(),
    );
  });

  /** A single ranked card match, so the detail panel has an Approve button to
   * press. The card-level ranking is unchanged by this tranche; what changed
   * is that pressing Approve now also has to name a printing. */
  function matchesFor(candidate: SnkrdunkCandidate): CandidateMatches {
    return {
      candidate,
      matches: [
        {
          card_id: 1,
          card_code: "OP01-001",
          name_en: "Monkey D. Luffy",
          name_jp: "モンキー・D・ルフィ",
          set_code: "OP01",
          rarity: "L",
          variant: "base",
          score: 93,
          confidence_label: "exact",
          ambiguous: false,
          explanation: { positive: ["exact card_code match"], negative: [], caps_applied: [] },
        },
      ],
    };
  }

  it("no longer offers one-click approval from a row", async () => {
    // Approval names an exact printing now, and a printing cannot be chosen
    // from a row in a list - so the row action is gone on purpose.
    const candidate = makeCandidate();
    fetchSnkrdunkCandidates.mockResolvedValue(listWith([candidate]));
    render(<SnkrdunkCandidatesPage />);

    await waitFor(() => expect(screen.getAllByText(/OP01-001/).length).toBeGreaterThan(0));

    expect(screen.queryByRole("button", { name: "Approve best" })).not.toBeInTheDocument();
    expect(approveCandidateMatch).not.toHaveBeenCalled();
  });

  it("approves with the printing the operator picked", async () => {
    const candidate = makeCandidate();
    fetchSnkrdunkCandidates.mockResolvedValue(listWith([candidate]));
    fetchCandidatePrintOptions.mockResolvedValue({
      candidate: {
        candidate_id: 1,
        source: "snkrdunk",
        title: "OP01-001 Luffy",
        source_url: "https://snkrdunk.com/cards/1",
        source_image_url: null,
        detected_card_code: "OP01-001",
        detected_set_code: "OP-01",
        detected_variant: "p1",
        detected_rarity: null,
        price_jpy: 1500,
      },
      options: [
        {
          card_print_id: 77,
          card_code: "OP01-001",
          name_en: "Monkey D. Luffy",
          name_jp: "モンキー・D・ルフィ",
          display_image: null,
          image_url: null,
          found_in_product: "OP-01",
          rarity: "Leader",
          special_print: null,
          printing: "Alt Art",
          art_ordinal: null,
          language: "jp",
          approvable: true,
          refusal_code: null,
          refusal_detail: null,
        },
      ],
      resolvable_card_print_id: 77,
      ambiguity_reason: null,
    });
    fetchCandidateMatches.mockResolvedValue(matchesFor(candidate));
    approveCandidateMatch.mockResolvedValue({
      ...candidate,
      match_status: "matched",
      matched_card_id: 1,
    });
    render(<SnkrdunkCandidatesPage />);

    await waitFor(() => expect(screen.getAllByText(/OP01-001/).length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: "Matches" }));

    await waitFor(() => expect(fetchCandidatePrintOptions).toHaveBeenCalledWith(1));
    await waitFor(() =>
      expect(screen.getByText("Which printing is this listing selling?")).toBeInTheDocument(),
    );
    // The single justifiable printing is pre-selected, so Approve is live.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(approveCandidateMatch).toHaveBeenCalledWith(1, 1, 77, undefined),
    );
  });

  it("will not approve while the evidence leaves the printing undecided", async () => {
    const candidate = makeCandidate();
    fetchSnkrdunkCandidates.mockResolvedValue(listWith([candidate]));
    fetchCandidatePrintOptions.mockResolvedValue({
      candidate: {
        candidate_id: 1,
        source: "snkrdunk",
        title: "OP01-001 Luffy",
        source_url: "https://snkrdunk.com/cards/1",
        source_image_url: null,
        detected_card_code: "OP01-001",
        detected_set_code: null,
        detected_variant: null,
        detected_rarity: null,
        price_jpy: 1500,
      },
      options: [1, 2].map((n) => ({
        card_print_id: 70 + n,
        card_code: "OP01-001",
        name_en: "Monkey D. Luffy",
        name_jp: "モンキー・D・ルフィ",
        display_image: null,
        image_url: null,
        found_in_product: "OP-01",
        rarity: "Leader",
        special_print: null,
        printing: n === 1 ? null : "Alt Art",
        art_ordinal: n,
        language: "jp",
        approvable: false,
        refusal_code: "evidence_cannot_distinguish_print",
        refusal_detail: "The source evidence does not distinguish these printings.",
      })),
      resolvable_card_print_id: null,
      ambiguity_reason: "0 of 2 printings can be justified from the stored evidence.",
    });
    fetchCandidateMatches.mockResolvedValue(matchesFor(candidate));
    render(<SnkrdunkCandidatesPage />);

    await waitFor(() => expect(screen.getAllByText(/OP01-001/).length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: "Matches" }));

    await waitFor(() =>
      expect(
        screen.getByText(/0 of 2 printings can be justified/),
      ).toBeInTheDocument(),
    );
    // Nothing is pre-selected, and neither rival can be picked.
    expect(screen.getByRole("button", { name: "Choose a printing" })).toBeDisabled();
    expect(approveCandidateMatch).not.toHaveBeenCalled();
  });

  it("rejects a candidate from a row action", async () => {
    const candidate = makeCandidate();
    fetchSnkrdunkCandidates.mockResolvedValue(listWith([candidate]));
    rejectCandidateMatch.mockResolvedValue({
      ...candidate,
      match_status: "rejected",
    });
    render(<SnkrdunkCandidatesPage />);

    await waitFor(() => expect(screen.getAllByText(/OP01-001/).length).toBeGreaterThan(0));

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));

    await waitFor(() =>
      expect(rejectCandidateMatch).toHaveBeenCalledWith(1, undefined),
    );
  });

  it("runs a rematch-all dry run and renders the result summary", async () => {
    fetchSnkrdunkCandidates.mockResolvedValue(EMPTY_LIST);
    const result: RematchAllResult = {
      would_update: 3,
      updated: 0,
      suggested: 2,
      ambiguous: 1,
      unmatched: 0,
      dry_run: true,
    };
    rematchAllCandidates.mockResolvedValue(result);
    render(<SnkrdunkCandidatesPage />);

    await waitFor(() => expect(fetchSnkrdunkCandidates).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Rematch all…" }));
    fireEvent.click(screen.getByRole("button", { name: "Dry run" }));

    await waitFor(() =>
      expect(rematchAllCandidates).toHaveBeenCalledWith({
        status: "all",
        limit: 100,
        dry_run: true,
      }),
    );
    await waitFor(() =>
      expect(screen.getByText(/would_update: 3/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/dry_run: true/)).toBeInTheDocument();
  });

  it("filters the status tabs to the new match_status vocabulary", async () => {
    fetchSnkrdunkCandidates.mockResolvedValue(EMPTY_LIST);
    render(<SnkrdunkCandidatesPage />);

    await waitFor(() => expect(fetchSnkrdunkCandidates).toHaveBeenCalled());

    for (const label of ["Unmatched", "Suggested", "Ambiguous", "Matched", "Rejected"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });
});
