import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

const { requireAdminSession } = vi.hoisted(() => ({ requireAdminSession: vi.fn() }));
vi.mock("@/lib/adminSession", () => ({ requireAdminSession }));

import { AdminOnlyPageLayout } from "./AdminOnlyPageLayout";
import OpportunitiesLayout from "@/app/market/opportunities/layout";
import ReportLayout from "@/app/market/report/layout";
import SignalEventsLayout from "@/app/market/signal-events/layout";
import SignalsLayout from "@/app/market/signals/layout";

describe("internal market pages are admin-only", () => {
  beforeEach(() => requireAdminSession.mockReset());

  it.each([
    ["/market/signals", SignalsLayout],
    ["/market/signal-events", SignalEventsLayout],
    ["/market/opportunities", OpportunitiesLayout],
    ["/market/report", ReportLayout],
  ])("%s uses the admin-only layout", (_route, layout) => {
    expect(layout).toBe(AdminOnlyPageLayout);
  });

  it("renders children for an admin session", async () => {
    requireAdminSession.mockResolvedValueOnce({ id: "staging-admin", email: "admin@example.com" });

    await expect(AdminOnlyPageLayout({ children: "page" })).resolves.toBe("page");
    expect(requireAdminSession).toHaveBeenCalledTimes(1);
  });

  it("does not render children when the admin check ends the request", async () => {
    // requireAdminSession() throws Next's notFound()/redirect() signal for a
    // collector or signed-out visitor; the layout must let it propagate.
    requireAdminSession.mockRejectedValueOnce(new Error("NEXT_NOT_FOUND"));

    await expect(AdminOnlyPageLayout({ children: "page" })).rejects.toThrow("NEXT_NOT_FOUND");
  });
});
