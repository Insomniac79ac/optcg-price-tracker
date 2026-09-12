import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signOut: vi.fn(),
}));
let currentPathname = "/";
beforeEach(() => { currentPathname = "/"; });
vi.mock("next/navigation", () => ({
  usePathname: () => currentPathname,
}));

import { TopBar } from "./TopBar";

describe("TopBar", () => {
  it("uses the canonical public compass wordmark while retaining navigation and search", () => {
    render(<TopBar />);
    const logo = screen.getByRole("link", { name: "CardPirate Atlas — Home" });
    expect(logo.querySelector("svg")).not.toBeNull();
    expect(logo.querySelector("img")).toBeNull();
    expect(logo).toHaveTextContent("CARDPIRATEATLAS");
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Search cards" })).toBeInTheDocument();
  });
  it("preserves supplied brand artwork on private admin tools", () => {
    currentPathname = "/admin/catalog-ops";
    render(<TopBar />);
    const link = screen.getByRole("link", { name: "CardPirate Atlas — Home" });
    const srcs = Array.from(link.querySelectorAll("img")).map((i) => i.getAttribute("src") ?? "");
    // Full lockup for desktop, square mark for mobile - both real assets from
    // public/brand, swapped by CSS rather than re-drawn at either size.
    expect(srcs.some((s) => s.includes("cardpirate-atlas-logo"))).toBe(true);
    expect(srcs.some((s) => s.includes("cardpirate-atlas-mark"))).toBe(true);
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/optcg vault|tcg vault/i);
  });

  it("links the product mark home with one accessible name, not a duplicated one", () => {
    render(<TopBar />);
    const link = screen.getByRole("link", { name: "CardPirate Atlas — Home" });
    expect(link).toHaveAttribute("href", "/");
    // The brand images are decorative (alt=""), so nothing of theirs may leak
    // into the link's accessible name (this previously produced
    // "CardPirate Atlas — HomeCardPirate Atlas").
    expect(link).toHaveAccessibleName("CardPirate Atlas — Home");
  });

  it("offers only public navigation destinations that already work", () => {
    render(<TopBar />);
    const nav = screen.getByRole("navigation", { name: "Public sections" });
    const hrefs = Array.from(nav.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    // /analytics is the current market landscape (Analytics 1A-B) - public,
    // and backed by three deliberately unauthenticated endpoints.
    expect(hrefs).toEqual(["/", "/cards", "/analytics"]);
    expect(Array.from(nav.querySelectorAll("a")).map((a) => a.textContent)).toEqual(["Home", "Cards", "Market"]);
    expect(screen.queryByRole("link", { name: "Discover" })).not.toBeInTheDocument();
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
