import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
}));

import { TopBar } from "./TopBar";

describe("TopBar", () => {
  it("renders the supplied brand artwork, not a text/SVG substitute or the old OPTCG/Vault wordmark", () => {
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
    expect(link.textContent?.trim()).toBe("");
  });

  it("offers only public navigation destinations that already work", () => {
    render(<TopBar />);
    const nav = screen.getByRole("navigation", { name: "Public sections" });
    const hrefs = Array.from(nav.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/", "/cards", "/market/movers"]);
    expect(hrefs).not.toContain("/admin");
  });

  it("does not reference 'signals' in the global search placeholder", () => {
    render(<TopBar />);
    expect(screen.getByText(/search cards, collection/i).textContent).not.toMatch(/signals/i);
  });
});
