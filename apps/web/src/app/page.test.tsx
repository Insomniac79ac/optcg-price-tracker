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
  // Guard: Discover must never reach for the legacy canonical-card catalogue
  // again. That payload carries no print identity, so nothing built from it
  // could link to an exact printing without guessing which one it meant.
  fetchCardsCatalogue: vi.fn(),
}));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, fetchSavedViews, fetchCardsCatalogue };
});

const { fetchPrintCatalogue } = vi.hoisted(() => ({ fetchPrintCatalogue: vi.fn() }));
vi.mock("@/lib/prints", async () => {
  const actual = await vi.importActual<typeof import("@/lib/prints")>("@/lib/prints");
  return { ...actual, fetchPrintCatalogue };
});

import type { PrintCatalogueItem } from "@/lib/prints";
import { useSession } from "next-auth/react";

import DiscoverPage from "./page";

/** Shaped on the real `GET /prints` staging payload. `card_print_id` is the
 * only identity this page has, and the only one it may route with. */
function makePrint(
  overrides: Partial<PrintCatalogueItem> & { card_print_id: number },
): PrintCatalogueItem {
  const { market_index: indexOverrides, ...rest } = overrides;
  return {
    canonical_card_id: 900 + overrides.card_print_id,
    card_code: `OP01-0${overrides.card_print_id}`,
    name_en: `Test Card ${overrides.card_print_id}`,
    name_jp: null,
    rarity: "R",
    card_type: "Character",
    treatment: "normal",
    language: "jp",
    release_product_code: "OP-01",
    image_url: null,
    display_image: null,
    verification_status: "verified",
    source_coverage: [],
    latest_observation_at: null,
    market_index: {
      card_print_id: overrides.card_print_id,
      index_version: 1,
      index_value_jpy: null,
      calculation_method: "median_of_sources",
      source_count: 0,
      coverage_status: "none",
      confidence: "low",
      source_values: [],
      auxiliary_values: [],
      freshest_observation_at: null,
      stalest_eligible_source_at: null,
      stale_sources: [],
      calculated_at: "2026-07-01T00:00:00Z",
      ...indexOverrides,
    },
    ...rest,
  };
}

const catalogueResponse = (items: PrintCatalogueItem[]) => ({
  items,
  total: items.length,
  limit: 100,
  offset: 0,
  pagination: { total: items.length, limit: 100, offset: 0, has_next: false, has_previous: false, next_offset: null, previous_offset: null },
  facets: { treatments: [], rarities: [], languages: [], verification_statuses: [] },
});

const mockedUseSession = vi.mocked(useSession);

afterEach(() => {
  vi.clearAllMocks();
  mockedUseSession.mockReturnValue({ data: null, status: "unauthenticated" } as ReturnType<typeof useSession>);
});

describe("DiscoverPage hero", () => {
  it("renders the hero heading and collector-voiced copy", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    expect(screen.getByText(/your collection has a story/i)).toBeInTheDocument();
    await waitFor(() => expect(fetchPrintCatalogue).toHaveBeenCalled());
  });

  it("links to /cards as the primary Explore the Atlas action", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    expect(screen.getByRole("link", { name: /explore the atlas/i })).toHaveAttribute("href", "/cards");
  });

  it("links to /market/movers as the secondary Market Index action", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    expect(screen.getByRole("link", { name: /view market index/i })).toHaveAttribute(
      "href",
      "/market/movers",
    );
  });

  it("shows real card artwork in the hero when the catalogue has images, capped at 3", async () => {
    const cards = [1, 2, 3, 4, 5].map((id) => makePrint({ card_print_id: id, image_url: `https://example.test/card-${id}.jpg` }));
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse(cards));
    render(<DiscoverPage />);

    const hero = await screen.findByTestId("hero-art");
    // { hidden: true } - the composition is intentionally aria-hidden
    // (decorative, see HeroArt's own comment), which excludes it from
    // getAllByRole's default accessibility-tree-only search.
    expect(within(hero).getAllByRole("img", { hidden: true })).toHaveLength(3);
  });

  it("prioritises printings with artwork over printings without", async () => {
    const cards = [
      makePrint({ card_print_id: 1, image_url: null }),
      makePrint({ card_print_id: 2, image_url: "https://example.test/card-2.jpg" }),
      makePrint({ card_print_id: 3, image_url: null }),
    ];
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse(cards));
    render(<DiscoverPage />);

    const hero = await screen.findByTestId("hero-art");
    expect(within(hero).getAllByRole("img", { hidden: true })).toHaveLength(1);
  });

  it("falls back to the branded placeholder (not a broken image) when nothing has artwork", async () => {
    const cards = [makePrint({ card_print_id: 1, image_url: null, card_code: "OP01-099" })];
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse(cards));
    render(<DiscoverPage />);

    const hero = await screen.findByTestId("hero-art");
    expect(within(hero).queryByRole("img", { hidden: true })).not.toBeInTheDocument();
    expect(within(hero).getByText("OP01-099")).toBeInTheDocument();
  });

  it("shows a stable skeleton (not a blank gap) while the catalogue loads", () => {
    fetchPrintCatalogue.mockReturnValue(new Promise(() => {})); // never resolves
    render(<DiscoverPage />);
    expect(screen.getByTestId("hero-art-loading")).toBeInTheDocument();
  });
});

describe("DiscoverPage Recent Finds", () => {
  it("shows a maximum of 4 prints, linking each to its exact print detail", async () => {
    const prints = [1, 2, 3, 4, 5, 6].map((id) => makePrint({ card_print_id: id }));
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse(prints));
    render(<DiscoverPage />);

    const links = await screen.findAllByRole("link", { name: /test card \d/i });
    expect(links).toHaveLength(4);
    expect(links[0]).toHaveAttribute("href", "/prints/1");
  });

  it("routes every find by card_print_id, never by a canonical card id", async () => {
    // canonical_card_id is deliberately a different number from
    // card_print_id in this fixture (900 + n), so a mix-up cannot pass
    // silently - it would produce /prints/901 rather than /prints/1.
    const prints = [1, 2, 3, 4].map((id) => makePrint({ card_print_id: id }));
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse(prints));
    render(<DiscoverPage />);

    const links = await screen.findAllByRole("link", { name: /test card \d/i });
    const hrefs = links.map((l) => l.getAttribute("href") ?? "");
    expect(hrefs).toEqual(["/prints/1", "/prints/2", "/prints/3", "/prints/4"]);
    expect(hrefs.some((h) => h.startsWith("/cards/"))).toBe(false);
  });

  it("keeps sibling printings of one card code distinct", async () => {
    const prints = [
      makePrint({ card_print_id: 3, card_code: "OP01-013", treatment: "parallel" }),
      makePrint({ card_print_id: 4, card_code: "OP01-013", treatment: "normal" }),
    ];
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse(prints));
    render(<DiscoverPage />);

    const links = await screen.findAllByRole("link", { name: /test card \d/i });
    const hrefs = links.map((l) => l.getAttribute("href"));
    expect(hrefs).toEqual(["/prints/3", "/prints/4"]);
    expect(new Set(hrefs).size).toBe(2);
  });

  it("does not read the legacy canonical-card catalogue at all", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([makePrint({ card_print_id: 1 })]));
    render(<DiscoverPage />);

    await screen.findAllByRole("link", { name: /test card 1/i });
    expect(fetchCardsCatalogue).not.toHaveBeenCalled();
  });

  it("covers the whole page with a single print-catalogue request", async () => {
    // Hero art, Recent Finds and the invitation stack all derive from one
    // response - no per-section refetch.
    fetchPrintCatalogue.mockResolvedValue(
      catalogueResponse([1, 2, 3].map((id) => makePrint({ card_print_id: id }))),
    );
    render(<DiscoverPage />);

    await screen.findAllByRole("link", { name: /test card 1/i });
    expect(fetchPrintCatalogue).toHaveBeenCalledTimes(1);
    expect(fetchPrintCatalogue).toHaveBeenCalledWith(expect.objectContaining({ sort: "updated" }));
  });

  it("shows fewer than 4 when the catalogue has fewer printings", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([makePrint({ card_print_id: 1 })]));
    render(<DiscoverPage />);

    expect(await screen.findAllByRole("link", { name: /test card 1/i })).toHaveLength(1);
  });

  it("never uses unsupported popularity/trending/hot wording", async () => {
    const cards = [1, 2, 3].map((id) => makePrint({ card_print_id: id }));
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse(cards));
    render(<DiscoverPage />);
    await screen.findAllByRole("link", { name: /test card \d/i });

    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/\btrending\b/i);
    expect(text).not.toMatch(/\bpopular\b/i);
    expect(text).not.toMatch(/\bhot\b/i);
    expect(text).not.toMatch(/\branking\b/i);
  });

  it("shows the 'waiting to be mapped' empty state when the catalogue is empty", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    expect(await screen.findByText(/the atlas is waiting to be mapped/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /browse cards/i })).toHaveAttribute("href", "/cards");
  });

  it("shows a concise error state with a working retry action, no stack trace", async () => {
    fetchPrintCatalogue.mockRejectedValueOnce(new Error("boom: internal db pool exhausted at 10.0.0.4"));
    render(<DiscoverPage />);

    const retry = await screen.findByRole("button", { name: /try again/i });
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/boom|10\.0\.0\.4|internal db/i);

    fetchPrintCatalogue.mockResolvedValueOnce(catalogueResponse([makePrint({ card_print_id: 1 })]));
    fireEvent.click(retry);
    expect(await screen.findByRole("link", { name: /test card 1/i })).toBeInTheDocument();
  });
});

describe("DiscoverPage collection invitation", () => {
  it("invites a signed-out visitor without promising a working sign-up", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    expect(await screen.findByText(/chart your collection/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /learn about collections/i })).toHaveAttribute(
      "href",
      "/sign-in",
    );
  });

  it("does not fabricate owned-card counts or completion percentages", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([]));
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
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([]));
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
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([]));
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
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    // Throws if more than one match - the assertion itself proves no duplicate.
    expect(screen.getByRole("link", { name: "CardPirate Atlas — Home" })).toHaveAttribute("href", "/");
  });

  it("renders no admin controls or admin navigation", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    expect(screen.queryByText(/admin/i)).not.toBeInTheDocument();
  });

  it("contains no dense data table above the fold", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<DiscoverPage />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("uses a single responsive DOM tree (Tailwind breakpoint classes), not a separate mobile branch", async () => {
    const cards = [1, 2, 3].map((id) => makePrint({ card_print_id: id, image_url: `https://example.test/card-${id}.jpg` }));
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse(cards));
    const { container } = render(<DiscoverPage />);
    await screen.findByTestId("hero-art");
    expect(container.innerHTML).toMatch(/hidden sm:block/);
    expect(container.innerHTML).toMatch(/hidden lg:block/);
  });
});
