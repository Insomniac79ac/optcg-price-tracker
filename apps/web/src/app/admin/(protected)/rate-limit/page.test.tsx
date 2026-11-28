import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

const fetchRateLimitStatus = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchRateLimitStatus: (...args: unknown[]) => fetchRateLimitStatus(...args),
  };
});

import { AdminAuthRequiredError } from "@/lib/api";

import RateLimitPage from "./page";

const SAMPLE = {
  enabled: true,
  windows: [{ group: "default", limit: 300, window_seconds: 60, active_keys: 4 }],
  started_at: "2026-11-27T14:21:00+00:00",
  platform_header_requests: 120,
  unverified_requests: 3,
  mismatch_requests: 0,
};

describe("RateLimitPage", () => {
  beforeEach(() => {
    fetchRateLimitStatus.mockReset();
  });

  it("renders the three counts, the windows and when counting started", async () => {
    fetchRateLimitStatus.mockResolvedValue(SAMPLE);
    render(<RateLimitPage />);

    await waitFor(() => expect(screen.getByTestId("count-platform_header_requests")).toHaveTextContent("120"));
    expect(screen.getByTestId("count-unverified_requests")).toHaveTextContent("3");
    expect(screen.getByTestId("count-mismatch_requests")).toHaveTextContent("0");
    expect(screen.getByText("default")).toBeInTheDocument();
    expect(screen.getByText(/27 Nov 2026, 22:21:00 MYT/)).toBeInTheDocument();
    expect(screen.getByText(/reset on every deploy or restart/)).toBeInTheDocument();
  });

  it("offers Refresh as its only action and re-fetches on click", async () => {
    fetchRateLimitStatus.mockResolvedValue(SAMPLE);
    render(<RateLimitPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument());
    expect(within(screen.getByRole("main")).getAllByRole("button")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(fetchRateLimitStatus).toHaveBeenCalledTimes(2));
  });

  it("shows the session-expired state when the admin session is missing", async () => {
    fetchRateLimitStatus.mockRejectedValue(new AdminAuthRequiredError());
    render(<RateLimitPage />);

    await waitFor(() =>
      expect(screen.getByText("Your admin session has expired or is no longer valid.")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("count-unverified_requests")).not.toBeInTheDocument();
  });
});
