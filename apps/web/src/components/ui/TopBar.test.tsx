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
    // sr-only full name from AtlasCompactMark.
    expect(screen.getByText("CardPirate Atlas")).toBeInTheDocument();
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/optcg vault|tcg vault/i);
  });

  it("links the product mark home", () => {
    render(<TopBar />);
    expect(screen.getByRole("link", { name: "CardPirate Atlas" })).toHaveAttribute("href", "/");
  });

  it("does not reference 'signals' in the global search placeholder", () => {
    render(<TopBar />);
    expect(screen.getByText(/search cards, collection/i).textContent).not.toMatch(/signals/i);
  });
});
