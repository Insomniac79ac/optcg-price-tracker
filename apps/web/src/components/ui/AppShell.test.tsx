import { fireEvent, render, screen, within } from "@testing-library/react";
import { act } from "react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

let clientSession: { data: { user: { role?: string; email?: string } } | null; status: string } = { data: null, status: "unauthenticated" };
let currentPathname = "/cards";

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(() => clientSession),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => currentPathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { AppShell } from "./AppShell";
import { AdminSurfaceProvider } from "@/components/admin/AdminSurfaceProvider";
import { AdminPageShell } from "@/components/admin/AdminPage";

function renderAuthorizedAdmin() {
  return render(<AdminSurfaceProvider><AppShell /></AdminSurfaceProvider>);
}

/** The persistent left-hand rail is what made the public product read as an
 * internal dashboard, so it now belongs to the admin surface only. These
 * guard that split in both directions - a regression in either one is a
 * product regression, not a styling detail. */
describe("AppShell navigation rail", () => {
  beforeEach(() => {
    currentPathname = "/cards";
    clientSession = { data: null, status: "unauthenticated" };
    HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
    HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  });

  it("renders no persistent rail on a public collector page", () => {
    const { container } = render(<AppShell />);
    expect(container.querySelector("[data-app-rail]")).toBeNull();
  });

  it("renders no persistent rail on the public landing page", () => {
    currentPathname = "/";
    const { container } = render(<AppShell />);
    expect(container.querySelector("[data-app-rail]")).toBeNull();
  });

  it("keeps the rail on the server-authorized admin surface", () => {
    clientSession = { data: { user: { role: "admin", email: "admin@example.com" } }, status: "authenticated" };
    currentPathname = "/admin/catalog-ops";
    const { container } = renderAuthorizedAdmin();
    expect(container.querySelector("[data-app-rail]")).not.toBeNull();
  });

  it.each([
    ["active", { data: { user: { role: "admin", email: "admin@example.com" } }, status: "authenticated" }],
    ["loading", { data: null, status: "loading" }],
    ["null", { data: null, status: "unauthenticated" }],
    ["error", { data: null, status: "unauthenticated" }],
  ])("keeps authorized admin chrome when the client session is %s", (_case, state) => {
    currentPathname = "/admin/source-mapping-proposals/1128";
    clientSession = state;
    const { container } = renderAuthorizedAdmin();
    expect(container.querySelectorAll("[data-app-header]")).toHaveLength(1);
    expect(container.querySelectorAll("[data-app-rail]")).toHaveLength(1);
    expect(container.querySelector("[data-admin-shell]")).not.toBeNull();
    expect(screen.getByText("ADMIN WORKSPACE")).toBeInTheDocument();
    expect(screen.getByText("Administrator")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Public sections" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sign in" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "CardPirate Atlas — Home" }).querySelector("img")).toBeNull();
    for (const group of ["Catalogue", "Sources & Pricing", "Operations", "System"]) {
      expect(screen.getByText(group)).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("button", { name: "Open admin navigation" }));
    expect(screen.getByRole("dialog", { name: "Admin navigation drawer" })).toBeInTheDocument();
    expect(screen.getAllByText("Sources & Pricing")).toHaveLength(2);
  });

  it("does not treat a client admin role as permission to render protected chrome", () => {
    currentPathname = "/admin";
    clientSession = { data: { user: { role: "admin" } }, status: "authenticated" };
    const { container } = render(<AppShell />);
    expect(container.querySelector("[data-app-rail]")).toBeNull();
    expect(screen.queryByText("ADMIN WORKSPACE")).not.toBeInTheDocument();
    expect(screen.queryByText("Sources & Pricing")).not.toBeInTheDocument();
  });

  it("keeps the login treatment outside the operational provider", () => {
    currentPathname = "/admin/login";
    const { container } = render(<AppShell />);
    expect(container.querySelector("[data-admin-shell]")).not.toBeNull();
    expect(container.querySelector("[data-app-rail]")).toBeNull();
    expect(screen.queryByText("ADMIN WORKSPACE")).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Public sections" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "CardPirate Atlas — Home" }).querySelector("img")).toBeNull();
  });

  it("renders one header and one rail when a protected admin page owns its shell", () => {
    currentPathname = "/admin";
    const { container } = render(<AdminSurfaceProvider><AdminPageShell><div>Protected body</div></AdminPageShell></AdminSurfaceProvider>);
    expect(container.querySelectorAll("[data-app-header]")).toHaveLength(1);
    expect(container.querySelectorAll("[data-app-rail]")).toHaveLength(1);
    expect(screen.getByText("Protected body")).toBeInTheDocument();
  });

  it("hydrates authorized chrome without a mismatch when the client session becomes null", async () => {
    currentPathname = "/admin";
    clientSession = { data: { user: { role: "admin" } }, status: "authenticated" };
    const ui = <AdminSurfaceProvider><AppShell /></AdminSurfaceProvider>;
    const host = document.createElement("div");
    host.innerHTML = renderToString(ui);
    document.body.appendChild(host);
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    clientSession = { data: null, status: "unauthenticated" };
    let root: ReturnType<typeof hydrateRoot> | undefined;
    try {
      await act(async () => { root = hydrateRoot(host, ui); });
      expect(host.querySelectorAll("[data-app-header]")).toHaveLength(1);
      expect(host.querySelectorAll("[data-app-rail]")).toHaveLength(1);
      expect(errors.mock.calls.flat().join(" ")).not.toMatch(/hydration|did not match/i);
    } finally {
      await act(async () => { root?.unmount(); });
      errors.mockRestore();
      host.remove();
    }
  });

  it("still offers public navigation in the header when the rail is gone", () => {
    const { container } = render(<AppShell />);
    expect(container.querySelector("[data-app-rail]")).toBeNull();

    const nav = screen.getByRole("navigation", { name: "Public sections" });
    const hrefs = Array.from(nav.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    // /analytics joined the public tier on 2026-09-06 (Analytics 1A-B).
    expect(hrefs).toEqual(["/", "/cards", "/analytics"]);
    expect(hrefs).not.toContain("/admin");
    expect(hrefs).not.toContain("/market/movers");
    // The legacy collector-data analytics pages stay out of navigation.
    expect(hrefs).not.toContain("/analytics/collection");
  });
});


describe("shared public shell", () => {
  it.each([["/", "Home"], ["/cards", "Cards"], ["/cards/code/OP01-001", "Cards"], ["/analytics", "Market"], ["/prints/1", "Cards"]])("shares branding and both navigation states on %s", (pathname, active) => {
    currentPathname = pathname;
    const { container } = render(<AppShell />);
    expect(container.querySelector("[data-public-shell]")).not.toBeNull();
    const logo = screen.getByRole("link", { name: "CardPirate Atlas — Home" });
    expect(logo.querySelector("svg")).not.toBeNull();
    expect(logo.querySelector("img")).toBeNull();
    expect(logo).toHaveTextContent("CARDPIRATEATLAS");
    for (const name of ["Public sections", "Mobile public sections"]) {
      const nav = screen.getByRole("navigation", { name });
      expect(within(nav).getAllByRole("link").map(a => a.getAttribute("href"))).toEqual(["/", "/cards", "/analytics"]);
      expect(nav.querySelectorAll("[aria-current]")).toHaveLength(1);
      expect(within(nav).getByRole("link", { name: active })).toHaveAttribute("aria-current", "page");
    }
    expect(screen.getByRole("button", { name: "Search cards" })).toBeInTheDocument();
  });

  it.each(["/collection", "/analytics/collection", "/search", "/sign-in"])("preserves private/account presentation on %s", (pathname) => {
    currentPathname = pathname;
    const { container } = render(<AppShell />);
    expect(container.querySelector("[data-public-shell]")).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Mobile public sections" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "CardPirate Atlas — Home" }).querySelector("img")).not.toBeNull();
  });

  it("updates the shared navigation and removes public scope when leaving browsing", () => {
    currentPathname = "/";
    const { container, rerender } = render(<AppShell />);
    for (const path of ["/cards", "/analytics", "/prints/1"]) {
      currentPathname = path;
      rerender(<AppShell />);
      expect(container.querySelectorAll("[data-public-shell]")).toHaveLength(1);
      expect(screen.getByRole("navigation", { name: "Mobile public sections" }).querySelectorAll("[aria-current]")).toHaveLength(1);
    }
    currentPathname = "/collection";
    rerender(<AppShell />);
    expect(container.querySelector("[data-public-shell]")).toBeNull();
  });
});
