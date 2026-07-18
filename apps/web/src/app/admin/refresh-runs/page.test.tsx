import { render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

const fetchRefreshRuns = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchRefreshRuns: (...args: unknown[]) => fetchRefreshRuns(...args),
  };
});

import RefreshRunsPage from "./page";

function emptyPage(total: number, offset: number, limit: number) {
  return {
    items: [],
    total,
    limit,
    offset,
    pagination: {
      total,
      limit,
      offset,
      has_next: offset + limit < total,
      has_previous: offset > 0,
      next_offset: offset + limit < total ? offset + limit : null,
      previous_offset: offset > 0 ? Math.max(offset - limit, 0) : null,
    },
  };
}

describe("RefreshRunsPage pagination", () => {
  beforeEach(() => {
    fetchRefreshRuns.mockReset();
  });

  it("does not crash when the run list is empty", async () => {
    fetchRefreshRuns.mockResolvedValue(emptyPage(0, 0, 100));
    render(<RefreshRunsPage />);
    await waitFor(() => expect(screen.getByText("No refresh runs found.")).toBeInTheDocument());
  });

  it("preserves the active status filter when paginating to the next page", async () => {
    fetchRefreshRuns.mockResolvedValue(emptyPage(350, 0, 100));
    render(<RefreshRunsPage />);

    await waitFor(() => expect(fetchRefreshRuns).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Failed" }));
    await waitFor(() =>
      expect(fetchRefreshRuns).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "failed", offset: 0 }),
      ),
    );

    fetchRefreshRuns.mockResolvedValue(emptyPage(350, 100, 100));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() =>
      expect(fetchRefreshRuns).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "failed", offset: 100, limit: 100 }),
      ),
    );
  });
});
