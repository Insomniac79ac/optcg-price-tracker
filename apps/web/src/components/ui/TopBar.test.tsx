import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: () => clientSession,
  signOut: vi.fn(),
}));
let currentPathname = "/";
let clientSession: { data: { user: { role?: string; email?: string } } | null; status: string };
beforeEach(() => {
  currentPathname = "/";
  clientSession = { data: null, status: "unauthenticated" };
});
vi.mock("next/navigation", () => ({
  usePathname: () => currentPathname,
}));

import { TopBar } from "./TopBar";
import { AdminSurfaceProvider } from "@/components/admin/AdminSurfaceProvider";

describe("TopBar", () => {
  describe.each([
    ["signed out", { data: null, status: "unauthenticated" }],
    ["collector", { data: { user: { email: "collector@example.com" } }, status: "authenticated" }],
    ["admin browsing public pages", { data: { user: { role: "admin" } }, status: "authenticated" }],
    ["loading", { data: null, status: "loading" }],
  ])("public hamburger — %s", (_label, session) => {
    it.each(["/", "/cards", "/cards/code/OP01-001", "/analytics", "/prints/1"])("switches from hamburger to header links at md on %s", (pathname) => {
      currentPathname = pathname;
      clientSession = session;
      render(<TopBar />);
      // jsdom cannot evaluate media queries. Guard the Tailwind visibility
      // contract here; Chrome checks exercise the compiled CSS at real widths.
      const toggle = screen.getByRole("button", { name: "Toggle navigation" });
      expect(toggle).toHaveClass("flex", "md:hidden");
      expect(toggle).not.toHaveClass("hidden", "lg:hidden", "xl:hidden");
      const nav = screen.getByRole("navigation", { name: "Public sections" });
      expect(nav).toHaveClass("hidden", "md:flex");
      expect(Array.from(nav.querySelectorAll("a")).map(a => a.textContent)).toEqual(["Home", "Card Prices", "Market"]);
      expect(screen.queryByRole("link", { name: "My Collection" })).not.toBeInTheDocument();
    });
  });

  it("uses the canonical public compass wordmark while retaining navigation and search", () => {
    render(<TopBar />);
    const logo = screen.getByRole("link", { name: "Card Pirate — Home" });
    expect(logo.querySelector("svg")).not.toBeNull();
    expect(logo.querySelector("img")).toBeNull();
    expect(logo).toHaveTextContent("CARDPIRATE");
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Search cards" })).toBeInTheDocument();
  });
  it("shares the compact Atlas compass and wordmark on admin tools", () => {
    currentPathname = "/admin/catalog-ops";
    render(<AdminSurfaceProvider><TopBar /></AdminSurfaceProvider>);
    const link = screen.getByRole("link", { name: "Card Pirate — Home" });
    expect(link.querySelector("svg")).not.toBeNull();
    expect(link.querySelector("img")).toBeNull();
    expect(link).toHaveTextContent("CARDPIRATE");
    expect(screen.queryByRole("navigation", { name: "Public sections" })).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "Open admin navigation" });
    expect(toggle).toHaveClass("flex", "xl:hidden");
    expect(toggle).not.toHaveClass("md:hidden", "lg:hidden");
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/optcg vault|tcg vault/i);
  });

  it("links the product mark home with one accessible name, not a duplicated one", () => {
    render(<TopBar />);
    const link = screen.getByRole("link", { name: "Card Pirate — Home" });
    expect(link).toHaveAttribute("href", "/");
    // The brand images are decorative (alt=""), so nothing of theirs may leak
    // into the link's accessible name (this previously produced
    // "Card Pirate — HomeCard Pirate").
    expect(link).toHaveAccessibleName("Card Pirate — Home");
  });

  it("offers only public navigation destinations that already work", () => {
    render(<TopBar />);
    const nav = screen.getByRole("navigation", { name: "Public sections" });
    const hrefs = Array.from(nav.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    // /analytics is the current market landscape (Analytics 1A-B) - public,
    // and backed by three deliberately unauthenticated endpoints.
    expect(hrefs).toEqual(["/", "/cards", "/analytics"]);
    expect(Array.from(nav.querySelectorAll("a")).map((a) => a.textContent)).toEqual(["Home", "Card Prices", "Market"]);
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
    expect(hrefs).not.toContain("/admin");
    // The seven legacy collector-data analytics pages gain no entry from it.
    for (const leaf of [
      "/analytics/collection",
      "/analytics/wishlist",
      "/analytics/grading",
      "/analytics/buy-decisions",
      "/analytics/sell-decisions",
      "/analytics/portfolio-risk",
      "/analytics/digest",
    ]) {
      expect(hrefs).not.toContain(leaf);
    }
    // Market Index is a value on every card, not a destination: its page was
    // a re-sorted copy of /cards and now redirects there (tranche 1A).
    expect(hrefs).not.toContain("/market/movers");
    expect(screen.queryByText("Market Index")).not.toBeInTheDocument();
  });

  it("does not promise search over anything the palette cannot actually search", () => {
    render(<TopBar />);
    // The palette searches cards (GET /search?types=cards) and the static
    // page/command registry - it has never searched collection, wishlist,
    // notes or signals, so the placeholder must not claim any of them.
    const placeholder = screen.getByText(/^search cards/i).textContent ?? "";
    expect(placeholder).not.toMatch(/collection|wishlist|signals|notes|grading/i);
  });

  it("keeps the keyboard-shortcuts control off touch viewports", () => {
    render(<TopBar />);
    // A keyboard-shortcuts reference is meaningless where there is no
    // keyboard, and the 390px bar needs the room for real 44px targets.
    const shortcuts = screen.getByRole("button", { name: "Keyboard shortcuts" });
    expect(shortcuts.className).toMatch(/\bhidden\b/);
    expect(shortcuts.className).toMatch(/lg:flex/);
  });
});
