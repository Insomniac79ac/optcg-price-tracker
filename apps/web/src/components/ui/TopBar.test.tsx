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
  it("renders the CardPirate Atlas product mark, not the old OPTCG/Vault wordmark", () => {
    render(<TopBar />);
    expect(screen.getByText("Atlas")).toBeInTheDocument();
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/optcg vault|tcg vault/i);
  });

  it("links the product mark home with one accessible name, not a duplicated one", () => {
    render(<TopBar />);
    const link = screen.getByRole("link", { name: "CardPirate Atlas — Home" });
    expect(link).toHaveAttribute("href", "/");
    // The mark's own sr-only text must not also leak into the link's name
    // (previously produced "CardPirate Atlas — HomeCardPirate Atlas").
    expect(link.textContent?.trim()).not.toContain("CardPirate AtlasCardPirate Atlas");
  });

  it("does not reference 'signals' in the global search placeholder", () => {
    render(<TopBar />);
    expect(screen.getByText(/search cards, collection/i).textContent).not.toMatch(/signals/i);
  });
});
