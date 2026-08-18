import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(() => ({ data: null, status: "unauthenticated" })),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/market/movers",
}));

const { fetchPrintCatalogue } = vi.hoisted(() => ({ fetchPrintCatalogue: vi.fn() }));
vi.mock("@/lib/prints", async () => {
  const actual = await vi.importActual<typeof import("@/lib/prints")>("@/lib/prints");
  return { ...actual, fetchPrintCatalogue };
});

// Guard: this page must never reach for the legacy canonical-card catalogue
// again - that payload carries no print identity, so anything built from it
// could not link to an exact printing without guessing.
const { fetchCardsCatalogue, fetchSavedViews } = vi.hoisted(() => ({
  fetchCardsCatalogue: vi.fn(),
  fetchSavedViews: vi.fn().mockResolvedValue({
    items: [],
    pagination: {
      total: 0,
      limit: 100,
      offset: 0,
      has_next: false,
      has_previous: false,
      next_offset: null,
      previous_offset: null,
    },
  }),
}));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, fetchCardsCatalogue, fetchSavedViews };
});

import type { PrintCatalogueItem } from "@/lib/prints";

import MarketIndexPage from "./page";

/** Shaped on the real `GET /prints` staging payload. */
function makePrint(
  overrides: Partial<PrintCatalogueItem> & { card_print_id: number },
): PrintCatalogueItem {
  const { market_index: indexOverrides, ...rest } = overrides;
  return {
    canonical_card_id: 4,
    card_code: "OP01-013",
    name_en: "Sanji",
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
    latest_observation_at: "2026-08-17T00:00:00Z",
    market_index: {
      card_print_id: overrides.card_print_id,
      index_version: 1,
      index_value_jpy: 810,
      calculation_method: "median_of_sources",
      source_count: 2,
      coverage_status: "full",
      confidence: "high",
      source_values: [],
      auxiliary_values: [],
      freshest_observation_at: "2026-08-17T00:00:00Z",
      stalest_eligible_source_at: null,
      stale_sources: [],
      calculated_at: "2026-08-17T00:00:00Z",
      ...indexOverrides,
    },
    ...rest,
  };
}

const catalogueResponse = (items: PrintCatalogueItem[]) => ({
  items,
  total: items.length,
  limit: 60,
  offset: 0,
  pagination: {
    total: items.length,
    limit: 60,
    offset: 0,
    has_next: false,
    has_previous: false,
    next_offset: null,
    previous_offset: null,
  },
  facets: { treatments: [], rarities: [], languages: [], verification_statuses: [] },
});

/** The public Market Index page, print-centric since the route-consistency
 * tranche: ranked by the API's own `index_desc` over exact printings. */
describe("Market Index page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("ranks the print catalogue, never the legacy canonical-card catalogue", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([makePrint({ card_print_id: 1 })]));
    render(<MarketIndexPage />);

    await waitFor(() => expect(fetchPrintCatalogue).toHaveBeenCalled());
    expect(fetchPrintCatalogue).toHaveBeenCalledWith(
      expect.objectContaining({ sort: "index_desc" }),
    );
    expect(fetchCardsCatalogue).not.toHaveBeenCalled();
  });

  it("links every tile to its exact print, never to a canonical card route", async () => {
    fetchPrintCatalogue.mockResolvedValue(
      catalogueResponse([
        makePrint({ card_print_id: 3, treatment: "parallel" }),
        makePrint({ card_print_id: 4 }),
      ]),
    );
    render(<MarketIndexPage />);

    const links = await screen.findAllByRole("link", { name: /Sanji/ });
    const hrefs = links.map((l) => l.getAttribute("href"));
    expect(hrefs).toEqual(["/prints/3", "/prints/4"]);
    expect(hrefs.some((h) => h?.startsWith("/cards/"))).toBe(false);
  });

  it("keeps sibling printings of one card code distinct and independently priced", async () => {
    fetchPrintCatalogue.mockResolvedValue(
      catalogueResponse([
        makePrint({
          card_print_id: 3,
          treatment: "parallel",
          market_index: { index_value_jpy: 1740 } as PrintCatalogueItem["market_index"],
        }),
        makePrint({
          card_print_id: 4,
          market_index: { index_value_jpy: 120 } as PrintCatalogueItem["market_index"],
        }),
      ]),
    );
    render(<MarketIndexPage />);

    const parallel = await screen.findByRole("link", { name: /Sanji, OP01-013, parallel/ });
    expect(parallel).toHaveAttribute("href", "/prints/3");
    expect(parallel.textContent).toContain("1,740");

    const base = screen.getByRole("link", { name: "Sanji, OP01-013, OP-01, R" });
    expect(base).toHaveAttribute("href", "/prints/4");
    expect(base.textContent).toContain("120");
  });

  it("issues exactly one print-catalogue request per load", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([makePrint({ card_print_id: 1 })]));
    render(<MarketIndexPage />);

    await screen.findByRole("link", { name: /Sanji/ });
    expect(fetchPrintCatalogue).toHaveBeenCalledTimes(1);
  });

  it("states the ranking basis without claiming price movement", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([makePrint({ card_print_id: 1 })]));
    render(<MarketIndexPage />);
    await screen.findByRole("link", { name: /Sanji/ });

    expect(screen.getByText(/Ranked by current Market Index/i)).toBeInTheDocument();
    // The payload carries no history, so nothing may imply a delta or trend.
    const body = document.body.textContent ?? "";
    expect(body).not.toMatch(/\b(gainers?|losers?|trending|% change|24h|rising|falling)\b/i);
  });

  it("shows a collector empty state rather than a blank grid", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([]));
    render(<MarketIndexPage />);

    expect(await screen.findByText("No printings yet")).toBeInTheDocument();
  });
});
