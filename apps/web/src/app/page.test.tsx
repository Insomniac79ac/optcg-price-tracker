import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(() => ({ data: null, status: "unauthenticated" })),
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
  fetchCardsCatalogue: vi.fn(),
}));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, fetchSavedViews, fetchCardsCatalogue };
});

import type { CardCatalogueItem } from "@/lib/api";
import { useSession } from "next-auth/react";

import DiscoverPage from "./page";

function makeCard(overrides: Partial<CardCatalogueItem> & { id: number }): CardCatalogueItem {
  return {
    card_code: `OP01-0${overrides.id}`,
    name_en: `Test Card ${overrides.id}`,
    name_jp: null,
    set_code: "OP01",
    rarity: "R",
    variant: null,
    language: "JP",
    image_url: null,
    tags: [],
    release_date: null,
    artist: null,
    character: null,
    color: null,
    card_type: null,
    cost: null,
    power: null,
    counter: null,
    attribute: null,
    effect_text: null,
    trigger_text: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    market_index: {
      card_id: overrides.id,
      index_version: 1,
      index_value_jpy: null,
      calculation_method: "mock",
      source_count: 0,
      coverage_status: "none",
      confidence: "low",
      source_values: [],
      auxiliary_values: [],
      freshest_observation_at: null,
      stalest_eligible_source_at: null,
      stale_sources: [],
      calculated_at: "2026-07-01T00:00:00Z",
    },
    ...overrides,
  };
}

const catalogueResponse = (items: CardCatalogueItem[]) => ({
  items,
  total: items.length,
  limit: 100,
  offset: 0,
  pagination: { total: items.length, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
  facets: { set_codes: [], rarities: [], languages: [], variants: [] },
});

const mockedUseSession = vi.mocked(useSession);

afterEach(() => {
  vi.clearAllMocks();
  mockedUseSession.mockReturnValue({ data: null, status: "unauthenticated" } as ReturnType<typeof useSession>);
});

describe("DiscoverPage hero", () => {
  it("renders the hero heading and collector-voiced copy", async () => {
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    expect(screen.getByText(/your collection has a story/i)).toBeInTheDocument();
    await waitFor(() => expect(fetchCardsCatalogue).toHaveBeenCalled());
  });

  it("links to /cards as the primary Explore the Atlas action", async () => {
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    expect(screen.getByRole("link", { name: /explore the atlas/i })).toHaveAttribute("href", "/cards");
  });

  it("links to /market/movers as the secondary Market Index action", async () => {
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    expect(screen.getByRole("link", { name: /view market index/i })).toHaveAttribute(
      "href",
      "/market/movers",
    );
  });

  it("shows real card artwork in the hero when the catalogue has images, capped at 3", async () => {
    const cards = [1, 2, 3, 4, 5].map((id) => makeCard({ id, image_url: `https://example.test/card-${id}.jpg` }));
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse(cards));
    render(<DiscoverPage />);

    const hero = await screen.findByTestId("hero-art");
    // { hidden: true } - the composition is intentionally aria-hidden
    // (decorative, see HeroArt's own comment), which excludes it from
    // getAllByRole's default accessibility-tree-only search.
    expect(within(hero).getAllByRole("img", { hidden: true })).toHaveLength(3);
  });

  it("prioritises cards with verified images over cards without", async () => {
    const cards = [
      makeCard({ id: 1, image_url: null }),
      makeCard({ id: 2, image_url: "https://example.test/card-2.jpg" }),
      makeCard({ id: 3, image_url: null }),
    ];
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse(cards));
    render(<DiscoverPage />);

    const hero = await screen.findByTestId("hero-art");
    expect(within(hero).getAllByRole("img", { hidden: true })).toHaveLength(1);
  });

  it("falls back to the branded placeholder (not a broken image) when no cards have artwork", async () => {
    const cards = [makeCard({ id: 1, image_url: null, card_code: "OP01-099" })];
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse(cards));
    render(<DiscoverPage />);

    const hero = await screen.findByTestId("hero-art");
    expect(within(hero).queryByRole("img", { hidden: true })).not.toBeInTheDocument();
    expect(within(hero).getByText("OP01-099")).toBeInTheDocument();
  });

  it("shows a stable skeleton (not a blank gap) while the catalogue loads", () => {
    fetchCardsCatalogue.mockReturnValue(new Promise(() => {})); // never resolves
    render(<DiscoverPage />);
    expect(screen.getByTestId("hero-art-loading")).toBeInTheDocument();
  });
});

describe("DiscoverPage Recent Finds", () => {
  it("shows a maximum of 4 cards, linking each to its detail page", async () => {
    const cards = [1, 2, 3, 4, 5, 6].map((id) => makeCard({ id }));
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse(cards));
    render(<DiscoverPage />);

    const links = await screen.findAllByRole("link", { name: /test card \d/i });
    expect(links).toHaveLength(4);
    expect(links[0]).toHaveAttribute("href", "/cards/1");
  });

  it("shows fewer than 4 when the catalogue has fewer cards", async () => {
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse([makeCard({ id: 1 })]));
    render(<DiscoverPage />);

    expect(await screen.findAllByRole("link", { name: /test card 1/i })).toHaveLength(1);
  });

  it("never uses unsupported popularity/trending/hot wording", async () => {
    const cards = [1, 2, 3].map((id) => makeCard({ id }));
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse(cards));
    render(<DiscoverPage />);
    await screen.findAllByRole("link", { name: /test card \d/i });

    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/\btrending\b/i);
    expect(text).not.toMatch(/\bpopular\b/i);
    expect(text).not.toMatch(/\bhot\b/i);
    expect(text).not.toMatch(/\branking\b/i);
  });

  it("shows the 'waiting to be mapped' empty state when the catalogue has no cards", async () => {
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    expect(await screen.findByText(/the atlas is waiting to be mapped/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /browse cards/i })).toHaveAttribute("href", "/cards");
  });

  it("shows a concise error state with a working retry action, no stack trace", async () => {
    fetchCardsCatalogue.mockRejectedValueOnce(new Error("boom: internal db pool exhausted at 10.0.0.4"));
    render(<DiscoverPage />);

    const retry = await screen.findByRole("button", { name: /try again/i });
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/boom|10\.0\.0\.4|internal db/i);

    fetchCardsCatalogue.mockResolvedValueOnce(catalogueResponse([makeCard({ id: 1 })]));
    fireEvent.click(retry);
    expect(await screen.findByRole("link", { name: /test card 1/i })).toBeInTheDocument();
  });
});

describe("DiscoverPage collection invitation", () => {
  it("invites a signed-out visitor without promising a working sign-up", async () => {
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    expect(await screen.findByText(/chart your collection/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /learn about collections/i })).toHaveAttribute(
      "href",
      "/sign-in",
    );
  });

  it("does not fabricate owned-card counts or completion percentages", async () => {
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    await screen.findByText(/chart your collection/i);
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/\d+%/);
    expect(text).not.toMatch(/\d+\s+cards owned/i);
  });

  it("shows the signed-in collection prompt instead when a session exists", async () => {
    mockedUseSession.mockReturnValue({
      data: { user: { name: "Test User" }, expires: "" },
      status: "authenticated",
    } as ReturnType<typeof useSession>);
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    // Sidebar nav also renders a plain "My Collection" link once
    // authenticated - match the invitation section's arrow-suffixed link
    // text specifically, not just any "My Collection" link on the page.
    expect(await screen.findByRole("link", { name: /my collection →/i })).toHaveAttribute(
      "href",
      "/collection",
    );
    expect(screen.queryByText(/chart your collection/i)).not.toBeInTheDocument();
  });
});

describe("DiscoverPage Market Index preview", () => {
  it("is brief and links onward, with no dense table or chart", async () => {
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    expect(await screen.findByText(/a clearer view of the market/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /explore the market index/i })).toHaveAttribute(
      "href",
      "/market/movers",
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("DiscoverPage accessibility and scope", () => {
  it("exposes exactly one accessible name for the header logo link", async () => {
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    // Throws if more than one match - the assertion itself proves no duplicate.
    expect(screen.getByRole("link", { name: "CardPirate Atlas — Home" })).toHaveAttribute("href", "/");
  });

  it("renders no admin controls or admin navigation", async () => {
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    expect(screen.queryByText(/admin/i)).not.toBeInTheDocument();
  });

  it("contains no dense data table above the fold", async () => {
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("uses a single responsive DOM tree (Tailwind breakpoint classes), not a separate mobile branch", async () => {
    const cards = [1, 2, 3].map((id) => makeCard({ id, image_url: `https://example.test/card-${id}.jpg` }));
    fetchCardsCatalogue.mockResolvedValue(catalogueResponse(cards));
    const { container } = render(<DiscoverPage />);
    await screen.findByTestId("hero-art");
    expect(container.innerHTML).toMatch(/hidden sm:block/);
    expect(container.innerHTML).toMatch(/hidden lg:block/);
  });
});
