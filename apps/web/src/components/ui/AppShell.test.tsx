import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let currentPathname = "/cards";

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(() => ({ data: null, status: "unauthenticated" })),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => currentPathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { AppShell } from "./AppShell";

/** The persistent left-hand rail is what made the public product read as an
 * internal dashboard, so it now belongs to the admin surface only. These
 * guard that split in both directions - a regression in either one is a
 * product regression, not a styling detail. */
describe("AppShell navigation rail", () => {
  beforeEach(() => {
    currentPathname = "/cards";
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

  it("keeps the rail on the admin surface", () => {
    currentPathname = "/admin/catalog-ops";
    const { container } = render(<AppShell />);
    expect(container.querySelector("[data-app-rail]")).not.toBeNull();
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

  it.each(["/admin/catalog-ops", "/collection", "/analytics/collection", "/search", "/sign-in"])("preserves private/account presentation on %s", (pathname) => {
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
