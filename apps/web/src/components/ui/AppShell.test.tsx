import { render, screen } from "@testing-library/react";
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
    expect(hrefs).toEqual(["/", "/cards"]);
    expect(hrefs).not.toContain("/admin");
    expect(hrefs).not.toContain("/market/movers");
  });
});
