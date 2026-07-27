import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const { requireAdminSession } = vi.hoisted(() => ({
  requireAdminSession: vi.fn(),
}));
vi.mock("@/lib/adminSession", () => ({ requireAdminSession }));
vi.mock("next/navigation", () => ({ usePathname: () => "/admin/backup" }));

import ProtectedAdminLayout from "./layout";

describe("ProtectedAdminLayout (shared server-side boundary for /admin/(protected)/*)", () => {
  it("renders children once requireAdminSession() resolves (admin session confirmed)", async () => {
    requireAdminSession.mockResolvedValueOnce({ id: "staging-admin", email: "admin@example.com" });

    const ui = await ProtectedAdminLayout({ children: <div>Page body content</div> });
    render(ui);

    expect(screen.getByText("Page body content")).toBeInTheDocument();
    expect(requireAdminSession).toHaveBeenCalledTimes(1);
  });

  it("propagates requireAdminSession()'s redirect/not-found rather than rendering children - e.g. a signed-out visitor hitting /admin/backup", async () => {
    requireAdminSession.mockRejectedValueOnce(new Error("NEXT_REDIRECT"));

    await expect(ProtectedAdminLayout({ children: <div>Backup</div> })).rejects.toThrow("NEXT_REDIRECT");
  });

  it("propagates a not-found rejection for a signed-in-but-non-admin visitor", async () => {
    requireAdminSession.mockRejectedValueOnce(new Error("NEXT_NOT_FOUND"));

    await expect(ProtectedAdminLayout({ children: <div>Cards</div> })).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("takes no route-specific input - one shared check for every page in this group", async () => {
    requireAdminSession.mockResolvedValueOnce({ id: "staging-admin", email: "admin@example.com" });

    await ProtectedAdminLayout({ children: <div /> });

    expect(requireAdminSession).toHaveBeenCalledWith();
  });
});
