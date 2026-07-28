import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
}));

const { fetchSavedViews, fetchCardsCatalogue } = vi.hoisted(() => ({
  fetchSavedViews: vi.fn().mockResolvedValue({
    items: [],
    pagination: { total: 0, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
  }),
  fetchCardsCatalogue: vi.fn().mockResolvedValue({
    items: [],
    total: 0,
    limit: 6,
    offset: 0,
    pagination: { total: 0, limit: 6, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
    facets: { set_codes: [], rarities: [], languages: [], variants: [] },
  }),
}));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, fetchSavedViews, fetchCardsCatalogue };
});

import DiscoverPage from "./page";

describe("DiscoverPage (public /)", () => {
  it("renders a real page instead of redirecting to /dashboard", () => {
    render(<DiscoverPage />);
    expect(screen.getByText(/your collection has a story/i)).toBeInTheDocument();
  });

  it("links to /cards as the primary Explore the Atlas action", () => {
    render(<DiscoverPage />);
    expect(screen.getByRole("link", { name: /explore the atlas/i })).toHaveAttribute("href", "/cards");
  });

  it("links to /market/movers as the Market Index action", () => {
    render(<DiscoverPage />);
    expect(screen.getByRole("link", { name: /view market index/i })).toHaveAttribute(
      "href",
      "/market/movers",
    );
  });

  it("invites a signed-out visitor to keep track of their cards, without promising a working sign-in", () => {
    render(<DiscoverPage />);
    expect(screen.getByText(/keep the cards that matter to you in one place/i)).toBeInTheDocument();
  });

  it("renders no admin controls or admin navigation", () => {
    render(<DiscoverPage />);
    expect(screen.queryByText(/admin/i)).not.toBeInTheDocument();
  });

  it("contains no dense data table above the fold", () => {
    render(<DiscoverPage />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
