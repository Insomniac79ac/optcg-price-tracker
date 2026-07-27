import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
}));

const fetchJobLocks = vi.fn();
const cleanupExpiredJobLocks = vi.fn();
const forceReleaseJobLock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchJobLocks: (...args: unknown[]) => fetchJobLocks(...args),
    cleanupExpiredJobLocks: (...args: unknown[]) => cleanupExpiredJobLocks(...args),
    forceReleaseJobLock: (...args: unknown[]) => forceReleaseJobLock(...args),
  };
});

import JobLocksPage from "./page";

const SAMPLE_LOCK = {
  lock_name: "market_workflow",
  owner_id: "market_workflow:abc-123",
  acquired_at: "2026-07-18T12:00:00Z",
  expires_at: "2026-07-18T13:00:00Z",
  status: "active" as const,
  metadata: { source: "yuyutei" },
};

describe("JobLocksPage", () => {
  beforeEach(() => {
    fetchJobLocks.mockReset();
    cleanupExpiredJobLocks.mockReset();
    forceReleaseJobLock.mockReset();
  });

  it("does not crash and shows an empty state when there are no active locks", async () => {
    fetchJobLocks.mockResolvedValue({ locks: [] });
    render(<JobLocksPage />);

    await waitFor(() => expect(screen.getByText("No active job locks.")).toBeInTheDocument());
  });

  it("renders active locks returned by the API", async () => {
    fetchJobLocks.mockResolvedValue({ locks: [SAMPLE_LOCK] });
    render(<JobLocksPage />);

    await waitFor(() => expect(screen.getByText("market_workflow")).toBeInTheDocument());
    expect(screen.getByText("market_workflow:abc-123")).toBeInTheDocument();
  });

  it("does not call force-release until RELEASE is typed to confirm", async () => {
    fetchJobLocks.mockResolvedValue({ locks: [SAMPLE_LOCK] });
    render(<JobLocksPage />);

    await waitFor(() => expect(screen.getByText("market_workflow")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Force release" }));
    const confirmButton = screen.getByRole("button", { name: "Confirm" });

    // Not yet typed - clicking Confirm must not call the API.
    fireEvent.click(confirmButton);
    expect(forceReleaseJobLock).not.toHaveBeenCalled();
    expect(screen.getByText("Type RELEASE to confirm.")).toBeInTheDocument();

    // Wrong text - still must not call the API.
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "release" } });
    fireEvent.click(confirmButton);
    expect(forceReleaseJobLock).not.toHaveBeenCalled();

    // Correct text - now it should call the API.
    fetchJobLocks.mockResolvedValue({ locks: [] });
    forceReleaseJobLock.mockResolvedValue({ released: true, lock_name: "market_workflow" });
    fireEvent.change(input, { target: { value: "RELEASE" } });
    fireEvent.click(confirmButton);

    await waitFor(() =>
      expect(forceReleaseJobLock).toHaveBeenCalledWith("market_workflow", "RELEASE"),
    );
    await waitFor(() =>
      expect(screen.getByText("Force-released lock: market_workflow")).toBeInTheDocument(),
    );
  });

  it("calls cleanup-expired and refetches locks", async () => {
    fetchJobLocks.mockResolvedValue({ locks: [] });
    cleanupExpiredJobLocks.mockResolvedValue({ cleaned_up_count: 2 });
    render(<JobLocksPage />);

    await waitFor(() => expect(screen.getByText("No active job locks.")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Cleanup expired locks" }));

    await waitFor(() => expect(cleanupExpiredJobLocks).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByText("Marked 2 expired lock(s) as expired.")).toBeInTheDocument(),
    );
  });
});
