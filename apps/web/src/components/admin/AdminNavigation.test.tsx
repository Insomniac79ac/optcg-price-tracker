import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Session } from "next-auth";

let pathname = "/admin/source-mapping-proposals/1128";
let session: Session | null = null;
vi.mock("next/navigation", () => ({ usePathname: () => pathname, useRouter: () => ({ push: vi.fn() }), useSearchParams: () => new URLSearchParams("page=4") }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: session, status: session ? "authenticated" : "unauthenticated" }), signOut: vi.fn() }));
import { AdminNavigation } from "./AdminNavigation";
import { ADMIN_NAVIGATION } from "./adminNavigation";
import { AppShell } from "@/components/ui/AppShell";

beforeEach(() => {
  pathname = "/admin/source-mapping-proposals/1128";
  session = { user: { role: "admin", email: "admin@example.com" }, sessionKind: "admin", expires: "2099-01-01" };
});

describe("Atlas admin shell", () => {
  it("preserves every admin page URL in the grouped route registry", () => {
    const root = path.resolve("src/app/admin/(protected)");
    const routes = ["/admin", ...readdirSync(root, { withFileTypes: true }).filter((entry) => entry.isDirectory()).map((entry) => `/admin/${entry.name}`)];
    const registered = ADMIN_NAVIGATION.flatMap((group) => group.routes.map(([href]) => href));
    expect([...registered].sort()).toEqual(routes.sort());
    expect(new Set(registered).size).toBe(registered.length);
    expect(readFileSync(path.join(root, "layout.tsx"), "utf8")).not.toContain("AdminSubNav");
  });
  it("expands the current group, marks the active parent and supports collapsing", () => {
    const { rerender } = render(<AdminNavigation />);
    for (const label of ["Catalogue", "Sources & Pricing", "Operations", "System"]) expect(screen.getByText(label)).toBeInTheDocument();
    const group = screen.getByText("Sources & Pricing").closest("details")!;
    expect(group.open).toBe(true);
    expect(screen.getByRole("link", { name: "Proposal Review" })).toHaveAttribute("aria-current", "page");
    fireEvent.click(screen.getByText("Sources & Pricing"));
    expect(group.open).toBe(false);
    pathname = "/admin/logs";
    rerender(<AdminNavigation />);
    expect(screen.getByText("System").closest("details")).toHaveAttribute("open");
    expect(screen.getByRole("link", { name: "Logs" })).toHaveAttribute("aria-current", "page");
  });
  it("uses the same groups in a modal mobile drawer with an explicit close action", () => {
    // jsdom has the element but not the browser's native modal methods.
    const show = vi.fn(function (this: HTMLDialogElement) { this.setAttribute("open", ""); });
    const close = vi.fn(function (this: HTMLDialogElement) { this.removeAttribute("open"); });
    Object.defineProperties(HTMLDialogElement.prototype, {
      showModal: { configurable: true, value: show }, close: { configurable: true, value: close },
    });
    try {
      render(<AppShell />);
      fireEvent.click(screen.getByRole("button", { name: "Open admin navigation" }));
      const drawer = screen.getByRole("dialog", { name: "Admin navigation drawer" });
      expect(show).toHaveBeenCalledOnce();
      for (const group of ADMIN_NAVIGATION) expect(within(drawer).getByText(group.label)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Open admin navigation" })).toHaveAttribute("aria-expanded", "true");
      fireEvent.click(within(drawer).getByRole("button", { name: "Close admin navigation" }));
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(close).toHaveBeenCalled();
      expect(screen.queryByRole("navigation", { name: "Mobile public sections" })).not.toBeInTheDocument();
    } finally { Reflect.deleteProperty(HTMLDialogElement.prototype, "showModal"); Reflect.deleteProperty(HTMLDialogElement.prototype, "close"); }
  });
  it("replaces admin access with reauthentication when the role expires", () => {
    const { container, rerender } = render(<AppShell />);
    expect(container.querySelector("[data-app-rail]")).not.toBeNull();
    session = { ...session!, user: { email: "admin@example.com" }, adminSessionExpired: true };
    rerender(<AppShell />);
    expect(container.querySelector("[data-app-rail]")).toBeNull();
    expect(screen.getByText("Admin session expired")).toBeInTheDocument();
    const href = new URL(screen.getByRole("link", { name: "Sign in again" }).getAttribute("href")!, "https://atlas.example");
    expect(href.searchParams.get("callbackUrl")).toBe(`${pathname}?page=4`);
    expect(href.searchParams.get("reason")).toBe("session-expired");
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
  });
  it.each([null, { user: { email: "collector@example.com" }, sessionKind: "collector", expires: "2099-01-01" } as Session])("does not reveal operational navigation to a non-admin", (value) => {
    session = value;
    const { container } = render(<AppShell />);
    expect(container.querySelector("[data-app-rail]")).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Admin navigation" })).not.toBeInTheDocument();
  });
});
