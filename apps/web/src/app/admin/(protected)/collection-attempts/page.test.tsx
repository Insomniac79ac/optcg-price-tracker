import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/admin/collection-attempts",
}));

const fetchCollectionAttempts = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchCollectionAttempts: (...args: unknown[]) => fetchCollectionAttempts(...args),
  };
});

import CollectionAttemptsPage from "./page";

type Attempt = import("@/lib/api").CollectionAttempt;

function attempt(overrides: Partial<Attempt> = {}): Attempt {
  return {
    id: 1,
    batch_run_id: "2ed196b16784",
    selection_ordinal: 1,
    source_id: 1,
    source_name: "yuyutei",
    source_card_mapping_id: 423,
    mapping_resolved: true,
    card_code: "OP01-004",
    card_print_id: 5997,
    selected_at: "2026-09-03T18:21:20Z",
    started_at: "2026-09-03T18:42:40Z",
    finished_at: "2026-09-03T18:42:46Z",
    duration_seconds: 6.5,
    status: "written",
    failure_stage: null,
    failure_reason: null,
    source_denied: false,
    price_observation_id: 1454,
    ...overrides,
  };
}

function payload(attempts: Attempt[], summaryOverrides = {}) {
  const total = attempts.length;
  return {
    summary: {
      total_attempts: total,
      started: attempts.filter((a) => a.started_at !== null).length,
      written: attempts.filter((a) => a.status === "written").length,
      skipped: attempts.filter((a) => a.status === "skipped").length,
      source_denied: attempts.filter((a) => a.source_denied).length,
      still_selected: attempts.filter((a) => a.status === "selected").length,
      by_status: {},
      by_failure_stage: {},
      earliest_selected_at: attempts[0]?.selected_at ?? null,
      latest_finished_at: attempts[0]?.finished_at ?? null,
      ...summaryOverrides,
    },
    attempts,
    limit: 100,
    offset: 0,
    pagination: {
      total,
      limit: 100,
      offset: 0,
      has_next: false,
      has_previous: false,
      next_offset: null,
      previous_offset: null,
    },
  };
}

describe("CollectionAttemptsPage", () => {
  beforeEach(() => {
    fetchCollectionAttempts.mockReset();
  });

  it("shows an explicit empty state before any run has recorded anything", async () => {
    fetchCollectionAttempts.mockResolvedValue(payload([]));

    render(<CollectionAttemptsPage />);

    await waitFor(() =>
      expect(screen.getByText("No collection attempts recorded yet.")).toBeInTheDocument(),
    );
    // No summary panel when there is nothing to summarise.
    expect(screen.queryByText("Batch summary")).not.toBeInTheDocument();
    expect(screen.queryByText("Summary (all attempts)")).not.toBeInTheDocument();
  });

  it("renders a populated table with card, batch and observation context", async () => {
    fetchCollectionAttempts.mockResolvedValue(payload([attempt()]));

    render(<CollectionAttemptsPage />);

    await waitFor(() => expect(screen.getByText("OP01-004")).toBeInTheDocument());
    expect(screen.getByText("written")).toBeInTheDocument();
    expect(screen.getByText("#423")).toBeInTheDocument();
    expect(screen.getByText("1454")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2ed196b16784" })).toBeInTheDocument();
  });

  it("renders the failure stage and reason for a failed attempt", async () => {
    fetchCollectionAttempts.mockResolvedValue(
      payload([
        attempt({
          id: 2,
          status: "validation_failed",
          failure_stage: "validation",
          failure_reason: "price_matches_card_code_or_id_digits:50",
          price_observation_id: null,
        }),
      ]),
    );

    render(<CollectionAttemptsPage />);

    await waitFor(() => expect(screen.getByText("validation_failed")).toBeInTheDocument());
    // Scoped to the table: "validation" is also a stage-filter <option>.
    const table = within(screen.getByRole("table"));
    expect(table.getByText("validation")).toBeInTheDocument();
    expect(
      table.getByText("price_matches_card_code_or_id_digits:50"),
    ).toBeInTheDocument();
  });

  it("shows a skipped attempt with no start and therefore no duration", async () => {
    fetchCollectionAttempts.mockResolvedValue(
      payload([
        attempt({
          id: 3,
          status: "skipped",
          started_at: null,
          finished_at: "2026-09-03T18:45:00Z",
          duration_seconds: null,
          source_denied: true,
          failure_reason: "source_denied:static_403",
          price_observation_id: null,
        }),
      ]),
    );

    render(<CollectionAttemptsPage />);

    await waitFor(() => expect(screen.getByText("skipped")).toBeInTheDocument());
    expect(screen.getByText("denied")).toBeInTheDocument();
    expect(screen.getByText("source_denied:static_403")).toBeInTheDocument();
    // duration and observation both render as an em dash rather than 0 or null
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("marks an attempt whose mapping can no longer be resolved", async () => {
    fetchCollectionAttempts.mockResolvedValue(
      payload([
        attempt({
          id: 4,
          mapping_resolved: false,
          card_code: null,
          card_print_id: null,
          source_card_mapping_id: 999999,
        }),
      ]),
    );

    render(<CollectionAttemptsPage />);

    await waitFor(() => expect(screen.getByText("unresolved")).toBeInTheDocument());
    // The stored id stays visible - it remains authoritative.
    expect(screen.getByText("#999999")).toBeInTheDocument();
  });

  it("shows the summary and refetches scoped to a batch when one is clicked", async () => {
    fetchCollectionAttempts.mockResolvedValue(
      payload([attempt()], { by_failure_stage: { homepage: 1 } }),
    );

    render(<CollectionAttemptsPage />);

    await waitFor(() =>
      expect(screen.getByText("Summary (all attempts)")).toBeInTheDocument(),
    );
    expect(screen.getByText("Selected")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "2ed196b16784" }));

    await waitFor(() =>
      expect(fetchCollectionAttempts).toHaveBeenLastCalledWith(
        expect.objectContaining({ batch_run_id: "2ed196b16784" }),
      ),
    );
    await waitFor(() => expect(screen.getByText("Batch summary")).toBeInTheDocument());
  });

  it("passes the status filter through to the API", async () => {
    fetchCollectionAttempts.mockResolvedValue(payload([attempt()]));

    render(<CollectionAttemptsPage />);
    await waitFor(() => expect(fetchCollectionAttempts).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Skipped" }));

    await waitFor(() =>
      expect(fetchCollectionAttempts).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "skipped" }),
      ),
    );
  });

  it("passes the failure stage and denied filters through to the API", async () => {
    fetchCollectionAttempts.mockResolvedValue(payload([attempt()]));

    render(<CollectionAttemptsPage />);
    await waitFor(() => expect(fetchCollectionAttempts).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("Failure stage"), {
      target: { value: "homepage" },
    });
    await waitFor(() =>
      expect(fetchCollectionAttempts).toHaveBeenLastCalledWith(
        expect.objectContaining({ failure_stage: "homepage" }),
      ),
    );

    fireEvent.click(screen.getByLabelText("Source denied only"));
    await waitFor(() =>
      expect(fetchCollectionAttempts).toHaveBeenLastCalledWith(
        expect.objectContaining({ source_denied: true }),
      ),
    );
  });

  it("surfaces a backend failure rather than rendering an empty table", async () => {
    fetchCollectionAttempts.mockRejectedValue(new Error("boom"));

    render(<CollectionAttemptsPage />);

    await waitFor(() =>
      expect(
        screen.getByText(/Failed to load collection attempts/),
      ).toBeInTheDocument(),
    );
  });
});
