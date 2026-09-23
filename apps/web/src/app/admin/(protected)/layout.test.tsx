import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { requireAdminSession, adminSurfaceRendered } = vi.hoisted(() => ({
  requireAdminSession: vi.fn(),
  adminSurfaceRendered: vi.fn(),
}));
vi.mock("@/lib/adminSession", () => ({ requireAdminSession }));
vi.mock("@/components/admin/AdminSurfaceProvider", () => ({
  AdminSurfaceProvider: ({ children }: { children: React.ReactNode }) => {
    adminSurfaceRendered();
    return <div data-admin-surface-provider="">{children}</div>;
  },
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/admin/backup" }));

import ProtectedAdminLayout from "./layout";

describe("ProtectedAdminLayout (shared server-side boundary for /admin/(protected)/*)", () => {
  beforeEach(() => {
    requireAdminSession.mockReset();
    adminSurfaceRendered.mockClear();
  });

  it("renders children once requireAdminSession() resolves (admin session confirmed)", async () => {
    requireAdminSession.mockResolvedValueOnce({ id: "staging-admin", email: "admin@example.com" });

    const ui = await ProtectedAdminLayout({ children: <div>Page body content</div> });
    render(ui);

    expect(screen.getByText("Page body content")).toBeInTheDocument();
    expect(screen.getByText("Page body content").closest("[data-admin-surface-provider]")).not.toBeNull();
    expect(adminSurfaceRendered).toHaveBeenCalledTimes(1);
    expect(requireAdminSession).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["signed-out", "NEXT_REDIRECT:/admin/login?callbackUrl=%2Fadmin%2Fbackup"],
    ["expired admin", "NEXT_REDIRECT:/admin/login?callbackUrl=%2Fadmin%2Fbackup&reason=session-expired"],
    ["collector", "NEXT_NOT_FOUND"],
  ])("never renders the provider or protected body when %s authorization fails", async (_case, failure) => {
    requireAdminSession.mockRejectedValueOnce(new Error(failure));
    await expect(ProtectedAdminLayout({ children: <div>Protected route labels</div> })).rejects.toThrow(failure);
    expect(adminSurfaceRendered).not.toHaveBeenCalled();
    expect(screen.queryByText("Protected route labels")).not.toBeInTheDocument();
    expect(screen.queryByText("ADMIN WORKSPACE")).not.toBeInTheDocument();
  });

  it("takes no route-specific input - one shared check for every page in this group", async () => {
    requireAdminSession.mockResolvedValueOnce({ id: "staging-admin", email: "admin@example.com" });

    await ProtectedAdminLayout({ children: <div /> });

    expect(requireAdminSession).toHaveBeenCalledWith();
  });
});
