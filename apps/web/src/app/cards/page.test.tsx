import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
let currentSearch = "";

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(() => ({ data: null, status: "unauthenticated" })),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/cards",
  useSearchParams: () => new URLSearchParams(currentSearch),
}));

const { fetchPrintCatalogue } = vi.hoisted(() => ({
  fetchPrintCatalogue: vi.fn(),
}));
vi.mock("@/lib/prints", async () => {
  const actual = await vi.importActual<typeof import("@/lib/prints")>("@/lib/prints");
  return { ...actual, fetchPrintCatalogue };
});

// Guard: if the catalogue ever reaches for a legacy card_id-keyed endpoint
// again, these spies fail the test rather than silently working.
const { fetchCardsCatalogue, fetchCardMarketIndex, fetchCards } = vi.hoisted(() => ({
  fetchCardsCatalogue: vi.fn(),
  fetchCardMarketIndex: vi.fn(),
  fetchCards: vi.fn(),
}));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, fetchCardsCatalogue, fetchCardMarketIndex, fetchCards };
});

import type {
  PrintCatalogueItem,
  PrintCatalogueList,
  PrintMarketIndex,
  PrintMarketIndexSourceValue,
} from "@/lib/prints";

import PrintsCataloguePage from "./page";

function sourceValue(
  source: string,
  valueJpy: number | null,
): PrintMarketIndexSourceValue {
  return {
    source,
    reference_type: source === "snkrdunk" ? "listing_floor" : "retail_sell",
    evidence_type: "listing",
    value_jpy: valueJpy,
    observed_at: valueJpy === null ? null : "2026-08-11T19:21:25.989165Z",
    sample_size: null,
    stale: false,
    eligible: true,
    fallback_used: false,
    ineligible_reason: null,
  };
}

function makePrint(
  overrides: Partial<PrintCatalogueItem> & { card_print_id: number },
): PrintCatalogueItem {
  const index: PrintMarketIndex = {
    card_print_id: overrides.card_print_id,
    index_version: 1,
    index_value_jpy: 1740,
    calculation_method: "median_of_sources",
    source_count: 2,
    coverage_status: "full",
    confidence: "high",
    source_values: [sourceValue("yuyutei", 1980), sourceValue("snkrdunk", 1500)],
    auxiliary_values: [],
    freshest_observation_at: "2026-08-11T19:21:25.989165Z",
    stalest_eligible_source_at: "2026-08-11T18:20:37.385148Z",
    stale_sources: [],
    calculated_at: "2026-08-12T13:45:05.031460Z",
    ...overrides.market_index,
  };

  return {
    canonical_card_id: 14,
    card_code: "OP01-013",
    name_en: "Sanji",
    name_jp: "サンジ",
    rarity: "R",
    card_type: "Character",
    treatment: "parallel",
    language: "jp",
    release_product_code: "OP-01",
    image_url: "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-013_p2.png",
    display_image: null,
    verification_status: "verified",
    source_coverage: ["snkrdunk", "yuyutei"],
    latest_observation_at: "2026-08-11T19:21:25.989165Z",
    ...overrides,
    market_index: index,
  };
}

function catalogueResponse(items: PrintCatalogueItem[]): PrintCatalogueList {
  return {
    items,
    total: items.length,
    limit: 24,
    offset: 0,
    pagination: {
      total: items.length,
      limit: 24,
      offset: 0,
      has_next: false,
      has_previous: false,
      next_offset: null,
      previous_offset: null,
    },
    facets: {
      treatments: ["normal", "parallel"],
      rarities: ["C", "L", "R", "SEC", "SR", "UC"],
      languages: ["jp"],
      verification_statuses: ["verified"],
    },
  };
}

const SANJI_PARALLEL = makePrint({ card_print_id: 3, treatment: "parallel" });
const SANJI_BASE = makePrint({
  card_print_id: 4,
  treatment: "normal",
  market_index: {
    index_value_jpy: 120,
    source_count: 1,
    coverage_status: "limited",
    confidence: "medium",
    source_values: [sourceValue("yuyutei", 120), sourceValue("snkrdunk", null)],
  } as PrintMarketIndex,
});

afterEach(() => {
  vi.clearAllMocks();
  currentSearch = "";
});

describe("print catalogue page", () => {
  it("loads from the print endpoint and never a legacy card_id-keyed one", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL]));
    render(<PrintsCataloguePage />);

    await waitFor(() => expect(fetchPrintCatalogue).toHaveBeenCalled());
    expect(fetchCardsCatalogue).not.toHaveBeenCalled();
    expect(fetchCardMarketIndex).not.toHaveBeenCalled();
    expect(fetchCards).not.toHaveBeenCalled();
  });

  it("links each tile to its print id, not a legacy card id", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL, SANJI_BASE]));
    render(<PrintsCataloguePage />);

    const links = await screen.findAllByRole("link", { name: /Sanji/ });
    const hrefs = links.map((l) => l.getAttribute("href"));
    expect(hrefs).toEqual(["/prints/3", "/prints/4"]);
    expect(hrefs.every((h) => h?.startsWith("/prints/"))).toBe(true);
  });

  it("shows Sanji base and parallel as two separate tiles with distinct prices", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL, SANJI_BASE]));
    render(<PrintsCataloguePage />);

    const parallel = await screen.findByRole("link", { name: /Sanji, OP01-013, parallel/ });
    const base = screen.getByRole("link", { name: /Sanji, OP01-013, OP-01/ });

    expect(parallel).not.toBe(base);
    expect(within(parallel).getByText("￥1,740")).toBeTruthy();
    expect(within(base).getByText("￥120")).toBeTruthy();
  });

  it("renders the two-source coverage state", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL]));
    render(<PrintsCataloguePage />);

    const tile = await screen.findByRole("link", { name: /Sanji/ });
    expect(within(tile).getByText("2 sources")).toBeTruthy();
  });

  it("names the single source on a limited-coverage print", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_BASE]));
    render(<PrintsCataloguePage />);

    const tile = await screen.findByRole("link", { name: /Sanji/ });
    expect(within(tile).getByText("Yuyu-Tei only")).toBeTruthy();
  });

  it("shows no fabricated trend, percentage, or sparkline", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL, SANJI_BASE]));
    const { container } = render(<PrintsCataloguePage />);

    await screen.findAllByRole("link", { name: /Sanji/ });
    expect(container.textContent).not.toMatch(/[+-]\d+(\.\d+)?%/);
    expect(container.querySelector("svg.sparkline")).toBeNull();
    expect(container.textContent).not.toMatch(/\b(24h|7d|30d)\b/);
  });

  it("renders card artwork with object-contain and never a crop", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL]));
    const { container } = render(<PrintsCataloguePage />);

    await screen.findByRole("link", { name: /Sanji/ });
    // Skip the shell/intro brand artwork - only the card image is under test.
    const img = container.querySelector("img:not([data-brand-asset])");
    expect(img).not.toBeNull();
    expect(img!.className).toContain("object-contain");
    expect(img!.className).not.toContain("object-cover");
    // Bandai's host refuses cross-site embedding (CORP: same-site), so the
    // artwork is re-served same-origin - still this print's exact image.
    expect(img!.getAttribute("src")).toBe(
      `/api/card-image?u=${encodeURIComponent(SANJI_PARALLEL.image_url!)}`,
    );
  });

  it("passes a card-code search to the server", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL, SANJI_BASE]));
    render(<PrintsCataloguePage />);
    await screen.findAllByRole("link", { name: /Sanji/ });

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "OP01-013" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(push).toHaveBeenCalledWith("/cards?q=OP01-013");
  });

  it("passes an English-name search to the server", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL]));
    render(<PrintsCataloguePage />);
    await screen.findAllByRole("link", { name: /Sanji/ });

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Sanji" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(push).toHaveBeenCalledWith("/cards?q=Sanji");
  });

  it("passes a Japanese-name search to the server", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL]));
    render(<PrintsCataloguePage />);
    await screen.findAllByRole("link", { name: /Sanji/ });

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "サンジ" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(push).toHaveBeenCalledWith(`/cards?q=${encodeURIComponent("サンジ")}`);
  });

  it("forwards a search term from the URL to the API, returning both siblings", async () => {
    currentSearch = "q=OP01-013";
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL, SANJI_BASE]));
    render(<PrintsCataloguePage />);

    await waitFor(() =>
      expect(fetchPrintCatalogue).toHaveBeenCalledWith(
        expect.objectContaining({ q: "OP01-013" }),
      ),
    );
    expect(await screen.findAllByRole("link", { name: /Sanji/ })).toHaveLength(2);
  });

  it("only offers treatment and rarity filters, both from real facets", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL]));
    render(<PrintsCataloguePage />);
    await screen.findByRole("link", { name: /Sanji/ });

    expect(screen.getByLabelText(/Treatment/)).toBeTruthy();
    expect(screen.getByLabelText(/Rarity/)).toBeTruthy();
    expect(screen.queryByLabelText(/^Set/)).toBeNull();
    expect(screen.queryByLabelText(/Language/)).toBeNull();
    expect(screen.queryByLabelText(/Variant/)).toBeNull();
  });

  it("filters by rarity through the toolbar select, with no separate chip strip", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL]));
    render(<PrintsCataloguePage />);
    await screen.findByRole("link", { name: /Sanji/ });

    // The rarity chip strip that briefly stood in for set navigation is gone:
    // no "All cards" reset control, and no group of rarity buttons.
    expect(screen.queryByRole("group", { name: "Rarity" })).toBeNull();
    expect(screen.queryByRole("button", { name: "All cards" })).toBeNull();

    // The underlying filter still works, from the same real facets.
    fireEvent.change(screen.getByLabelText(/Rarity/), { target: { value: "SEC" } });
    expect(push).toHaveBeenCalledWith("/cards?rarity=SEC");
  });

  it("sends the treatment filter to the server", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL]));
    render(<PrintsCataloguePage />);
    await screen.findByRole("link", { name: /Sanji/ });

    fireEvent.change(screen.getByLabelText(/Treatment/), { target: { value: "parallel" } });
    expect(push).toHaveBeenCalledWith("/cards?treatment=parallel");
  });

  it("draws the intro card fan from the first three loaded prints, with no extra request", async () => {
    const three = [
      SANJI_PARALLEL,
      SANJI_BASE,
      makePrint({ card_print_id: 9, card_code: "OP01-001", name_en: "Roronoa Zoro" }),
    ];
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse(three));
    const { container } = render(<PrintsCataloguePage />);
    await screen.findAllByRole("link", { name: /Sanji/ });

    // Atmosphere only: the fan is aria-hidden and holds no links, so the
    // three real, labelled copies of these cards stay in the grid below.
    const fan = container.querySelector("[data-hero-fan]");
    expect(fan).not.toBeNull();
    expect(fan!.getAttribute("aria-hidden")).toBe("true");
    expect(fan!.querySelectorAll("a")).toHaveLength(0);
    expect(fan!.querySelectorAll("img")).toHaveLength(3);
    // No card names or prices in the composition.
    expect(fan!.textContent).not.toMatch(/Sanji|Zoro|¥/);

    // Decoration must never cost a request - the page fetched exactly once.
    expect(fetchPrintCatalogue).toHaveBeenCalledTimes(1);
  });

  it("omits the intro card fan rather than composing it from too few prints", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL, SANJI_BASE]));
    const { container } = render(<PrintsCataloguePage />);
    await screen.findAllByRole("link", { name: /Sanji/ });

    expect(container.querySelector("[data-hero-fan]")).toBeNull();
  });

  it("uses no mock or demo dataset when the API returns nothing", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([]));
    const { container } = render(<PrintsCataloguePage />);

    await waitFor(() => expect(fetchPrintCatalogue).toHaveBeenCalled());
    await screen.findByText(/No cards yet/);
    // Brand chrome (header lockup, intro texture) is tagged
    // data-brand-asset; any other <img> would have to be card artwork, and
    // there is no card to draw - the intro fan needs three prints and gets
    // none here.
    expect(container.querySelectorAll("img:not([data-brand-asset])")).toHaveLength(0);
  });
});
