import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

let currentSearch = "";

/** The page commits catalogue state with the native History API rather than
 * router.push - see the `navigate` comment in ./page.tsx for why. These spies
 * are what a navigation looks like from a test's point of view. */
const pushState = vi.spyOn(window.history, "pushState");
// jsdom has no layout, so window.scrollTo is unimplemented and would log on
// every navigation.
vi.spyOn(window, "scrollTo").mockImplementation(() => {});

/** Every URL the page has navigated to, in order. */
function navigations(): string[] {
  return pushState.mock.calls.map((call) => String(call[2]));
}

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(() => ({ data: null, status: "unauthenticated" })),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  // The page itself no longer routes through useRouter, but AppShell (the
  // header) still does for its "g then <key>" goto shortcuts.
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
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
    original_set_code: "OP-01",
    official_asset_variant: "base",
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
      // Exactly what GET /prints publishes now: the two raw SP tokens are
      // folded server-side into one SP CARD value.
      rarities: ["C", "L", "P", "R", "SEC", "SP CARD", "SR", "TR", "UC"],
      languages: ["jp"],
      verification_statuses: ["verified"],
    },
  };
}

const SANJI_PARALLEL = makePrint({
  card_print_id: 3,
  treatment: "parallel",
  official_asset_variant: "p1",
});
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

/** Six distinct prints - distinct ids, codes and artwork - so the intro fan
 * has a real catalogue to rotate through rather than one card repeated. */
const CATALOGUE: PrintCatalogueItem[] = Array.from({ length: 6 }, (_, i) =>
  makePrint({
    card_print_id: 40 + i,
    card_code: `OP0${i + 1}-00${i + 1}`,
    image_url: `https://www.onepiece-cardgame.com/images/cardlist/card/art-${i}.png`,
  }),
);

/** The <img> sources actually drawn in the hero fan, in DOM order. */
function fanImageSources(container: HTMLElement): string[] {
  const fan = container.querySelector("[data-hero-fan]");
  if (!fan) return [];
  return [...fan.querySelectorAll("img")].map((img) => img.getAttribute("src") ?? "");
}

/** The slots actually drawn in the hero fan, in DOM order. */
function fanPositions(container: HTMLElement): string[] {
  const fan = container.querySelector("[data-hero-fan]");
  if (!fan) return [];
  return [...fan.querySelectorAll("[data-hero-fan-position]")].map(
    (el) => el.getAttribute("data-hero-fan-position") ?? "",
  );
}

/** Prose mentions a card code or a URL all the time; code must not. */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

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

    // The tiles are told apart by the printing type derived from Bandai's
    // asset variant, not by the raw Atlas treatment word. Rarity comes first
    // in the accessible name because rarity, special print and printing are
    // stated in that order everywhere - see PrintCardTile.
    const parallel = await screen.findByRole("link", {
      name: /^Sanji, OP01-013, Rare, Alt Art, found in OP-01/,
    });
    const base = screen.getByRole("link", { name: /^Sanji, OP01-013, Rare, found in OP-01/ });

    expect(parallel).not.toBe(base);
    // Each tile carries only its own print's money. The base tile shows ￥120
    // twice on purpose (its index, and the single source that produced it),
    // so distinctness is asserted as "neither tile shows the other's value".
    expect(within(parallel).getByText("￥1,740")).toBeTruthy();
    expect(within(parallel).queryByText("￥120")).toBeNull();
    expect(within(base).getAllByText("￥120").length).toBeGreaterThan(0);
    expect(within(base).queryByText("￥1,740")).toBeNull();
  });

  it("renders the two-source coverage state as both real source prices", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL]));
    render(<PrintsCataloguePage />);

    const tile = await screen.findByRole("link", { name: /Sanji/ });
    // The Market Index, then the two sources that actually produced it - the
    // per-source rows are what state the coverage on the tile.
    expect(within(tile).getByText("Market Index")).toBeTruthy();
    expect(within(tile).getByText("￥1,740")).toBeTruthy();
    expect(within(tile).getByText("Yuyu-Tei")).toBeTruthy();
    expect(within(tile).getByText("￥1,980")).toBeTruthy();
    expect(within(tile).getByText("SNKRDUNK")).toBeTruthy();
    expect(within(tile).getByText("￥1,500")).toBeTruthy();
  });

  it("never lets a one-source index read as a two-source consensus", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_BASE]));
    render(<PrintsCataloguePage />);

    const tile = await screen.findByRole("link", { name: /Sanji/ });
    // Only the source that reported gets a row. SNKRDUNK contributed no
    // value for this print, so it must not appear at all - not as a row, not
    // as a dash, and certainly not as ¥0.
    expect(within(tile).getByText("Yuyu-Tei")).toBeTruthy();
    expect(within(tile).getAllByText("￥120").length).toBeGreaterThan(0);
    expect(within(tile).queryByText("SNKRDUNK")).toBeNull();
    expect(tile.textContent).not.toMatch(/￥0\b/);
  });

  it("shows no price at all rather than ¥0 when the index is unavailable", async () => {
    const noIndex = makePrint({
      card_print_id: 11,
      market_index: {
        index_value_jpy: null,
        source_count: 0,
        coverage_status: "none",
        confidence: "low",
        source_values: [sourceValue("yuyutei", null), sourceValue("snkrdunk", null)],
      } as PrintMarketIndex,
    });
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([noIndex]));
    render(<PrintsCataloguePage />);

    const tile = await screen.findByRole("link", { name: /Sanji/ });
    expect(within(tile).getByText("Index unavailable")).toBeTruthy();
    expect(tile.textContent).not.toMatch(/￥/);
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
    // The tile's own image specifically: the intro fan now draws real card
    // artwork too, and it must not be what this assertion lands on.
    const img = container.querySelector('a[href^="/prints/"] img');
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

    expect(navigations()).toEqual(["/cards?q=OP01-013"]);
  });

  it("passes an English-name search to the server", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL]));
    render(<PrintsCataloguePage />);
    await screen.findAllByRole("link", { name: /Sanji/ });

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Sanji" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(navigations()).toEqual(["/cards?q=Sanji"]);
  });

  it("passes a Japanese-name search to the server", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL]));
    render(<PrintsCataloguePage />);
    await screen.findAllByRole("link", { name: /Sanji/ });

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "サンジ" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(navigations()).toEqual([`/cards?q=${encodeURIComponent("サンジ")}`]);
  });

  it("does not search while the visitor is still typing", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL, SANJI_BASE]));
    render(<PrintsCataloguePage />);
    await screen.findAllByRole("link", { name: /Sanji/ });
    const callsAfterLoad = fetchPrintCatalogue.mock.calls.length;

    // Eight characters, no submit: still one page load's worth of requests
    // and not one navigation. Clearing is the only edit that commits itself.
    for (const value of ["O", "OP", "OP0", "OP01", "OP01-", "OP01-0", "OP01-01", "OP01-013"]) {
      fireEvent.change(screen.getByRole("searchbox"), { target: { value } });
    }

    expect(navigations()).toEqual([]);
    expect(fetchPrintCatalogue.mock.calls.length).toBe(callsAfterLoad);
  });

  it("submits on Enter as well as the Search button", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL]));
    render(<PrintsCataloguePage />);
    await screen.findAllByRole("link", { name: /Sanji/ });

    const box = screen.getByRole("searchbox");
    fireEvent.change(box, { target: { value: "Sanji" } });
    fireEvent.submit(box.closest("form")!);

    expect(navigations()).toEqual(["/cards?q=Sanji"]);
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
    // no "All cards" reset control, and no rarity buttons. Asserted on buttons
    // rather than on a group role, because the select's own "Rarity"/"Special
    // print" <optgroup>s legitimately carry that role now.
    expect(screen.queryByRole("button", { name: "All cards" })).toBeNull();
    for (const label of ["Common", "Rare", "Super Rare", "Secret Rare", "SP Card"]) {
      expect(screen.queryByRole("button", { name: label }), `${label} chip`).toBeNull();
    }

    // The underlying filter still works, from the same real facets.
    fireEvent.change(screen.getByLabelText(/Rarity/), { target: { value: "SEC" } });
    expect(navigations()).toEqual(["/cards?rarity=SEC"]);
  });

  it("offers exactly one SP Card option, never one per source token", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL]));
    render(<PrintsCataloguePage />);
    await screen.findByRole("link", { name: /Sanji/ });

    const options = Array.from(
      screen.getByLabelText(/Rarity/).querySelectorAll("option"),
    ).map((option) => option.textContent);

    expect(options.filter((label) => label === "SP Card")).toHaveLength(1);
    // Never the disambiguated pair the raw tokens used to produce...
    expect(options).not.toContain("SP Card (SPカード)");
    expect(options).not.toContain("SP Card (SP P)");
    // ...and no raw source token reaches a catalogue-facing filter at all.
    for (const label of options) {
      expect(label).not.toContain("SPカード");
      expect(label).not.toContain("SP P");
    }
  });

  it("files the special prints under their own optgroup, not among the rarities", async () => {
    // Listing "SP Card" inline between Rare and Super Rare is exactly what
    // made an SP print read as though SP Card were its scarcity tier.
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL]));
    render(<PrintsCataloguePage />);
    await screen.findByRole("link", { name: /Sanji/ });

    const select = screen.getByLabelText(/Rarity/);
    const groups = Array.from(select.querySelectorAll("optgroup"));
    const byLabel = Object.fromEntries(
      groups.map((group) => [
        group.getAttribute("label"),
        Array.from(group.querySelectorAll("option")).map((o) => o.textContent),
      ]),
    );

    expect(byLabel["Rarity"]).toEqual([
      "Common", "Leader", "Promo", "Rare", "Secret Rare", "Super Rare", "Uncommon",
    ]);
    expect(byLabel["Special print"]).toEqual(["SP Card", "Treasure Rare"]);
  });

  it("sends the single SP Card value to the server verbatim", async () => {
    // The value is the API's own facet, and the API expands it to both source
    // tokens - so the browser neither merges nor rewrites anything.
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL]));
    render(<PrintsCataloguePage />);
    await screen.findByRole("link", { name: /Sanji/ });

    fireEvent.change(screen.getByLabelText(/Rarity/), { target: { value: "SP CARD" } });

    expect(navigations()).toEqual(["/cards?rarity=SP+CARD"]);
  });

  it("sends the treatment filter to the server", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL]));
    render(<PrintsCataloguePage />);
    await screen.findByRole("link", { name: /Sanji/ });

    fireEvent.change(screen.getByLabelText(/Treatment/), { target: { value: "parallel" } });
    expect(navigations()).toEqual(["/cards?treatment=parallel"]);
  });

  it("draws the intro card fan from prints the page already loaded, with no extra request", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse(CATALOGUE));
    const { container } = render(<PrintsCataloguePage />);
    await screen.findAllByRole("link", { name: /Sanji/ });

    // Atmosphere only: the fan is aria-hidden and holds no links, so the
    // real, labelled copies of these cards stay in the grid below.
    const fan = container.querySelector("[data-hero-fan]");
    expect(fan).not.toBeNull();
    expect(fan!.getAttribute("aria-hidden")).toBe("true");
    expect(fan!.querySelectorAll("a")).toHaveLength(0);
    expect(fan!.querySelectorAll("img")).toHaveLength(3);
    // No card names or prices in the composition.
    expect(fan!.textContent).not.toMatch(/Sanji|Zoro|¥/);

    // Every card in it is one of the prints the response actually carried -
    // nothing invented, nothing fetched separately.
    const loaded = new Set(CATALOGUE.map((item) => item.image_url));
    for (const src of fanImageSources(container)) {
      expect([...loaded].some((url) => src.includes(encodeURIComponent(url!)))).toBe(true);
    }

    // Decoration must never cost a request - the page fetched exactly once.
    expect(fetchPrintCatalogue).toHaveBeenCalledTimes(1);
  });

  it("fills the fan by position: one front card over two behind it", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse(CATALOGUE));
    const { container } = render(<PrintsCataloguePage />);
    await screen.findAllByRole("link", { name: /Sanji/ });

    const fan = container.querySelector("[data-hero-fan]")!;
    const positions = [...fan.querySelectorAll("[data-hero-fan-position]")].map((el) =>
      el.getAttribute("data-hero-fan-position"),
    );
    // The slots are fixed geometry; only the artwork in them rotates.
    expect(positions).toEqual(["back-left", "back-right", "front"]);
    const front = fan.querySelector('[data-hero-fan-position="front"]')!;
    expect(front.className).toContain("-translate-x-1/2");
    expect(front.querySelectorAll("img")).toHaveLength(1);
  });

  it("keeps the same fan when the visitor changes treatment, rarity or sort", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse(CATALOGUE));
    const { container, rerender } = render(<PrintsCataloguePage />);
    await screen.findAllByRole("link", { name: /Sanji/ });
    const before = fanImageSources(container);
    expect(before).toHaveLength(3);

    // Now narrow the catalogue hard: a filtered response that shares no
    // print with the fan at all. The fan represents the catalogue, not the
    // current view, so it must not follow.
    currentSearch = "rarity=SEC&treatment=parallel&sort=index_desc";
    fetchPrintCatalogue.mockResolvedValue(
      catalogueResponse([makePrint({ card_print_id: 99, card_code: "OP09-099" })]),
    );
    rerender(<PrintsCataloguePage />);
    await waitFor(() => expect(fetchPrintCatalogue).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(fetchPrintCatalogue).toHaveBeenLastCalledWith(
        expect.objectContaining({ rarity: "SEC", treatment: "parallel", sort: "index_desc" }),
      ),
    );

    expect(fanImageSources(container)).toEqual(before);
  });

  it("hides the fan cleanly when no print has a usable image", async () => {
    const imageless = CATALOGUE.map((item) =>
      makePrint({ ...item, image_url: null, display_image: null }),
    );
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse(imageless));
    const { container } = render(<PrintsCataloguePage />);
    await screen.findAllByRole("link", { name: /Sanji/ });

    // No fan, and no placeholder or empty shell standing in for one.
    expect(container.querySelector("[data-hero-fan]")).toBeNull();
    expect(container.querySelector("[data-hero-fan-position]")).toBeNull();
    expect(fanImageSources(container)).toEqual([]);
  });

  it("draws a two-card fan when only two prints are eligible", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse(CATALOGUE.slice(0, 2)));
    const { container } = render(<PrintsCataloguePage />);
    await screen.findAllByRole("link", { name: /Sanji/ });

    // Both real prints, drawn once each - no third slot, no repeat to fill it.
    const sources = fanImageSources(container);
    expect(sources).toHaveLength(2);
    expect(new Set(sources).size).toBe(2);
    expect(fanPositions(container)).toEqual(["back-left", "front"]);
  });

  it("draws a single card when only one print is eligible", async () => {
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse(CATALOGUE.slice(0, 1)));
    const { container } = render(<PrintsCataloguePage />);
    await screen.findAllByRole("link", { name: /Sanji/ });

    expect(fanImageSources(container)).toHaveLength(1);
    // The one card fronts the composition and sits on the centre line.
    expect(fanPositions(container)).toEqual(["front"]);
    const front = container.querySelector('[data-hero-fan-position="front"]')!;
    expect(front.className).toContain("left-1/2");
    expect(front.className).toContain("-translate-x-1/2");
  });

  it("skips prints whose image is known not to be that exact print", async () => {
    // Three prints, but one carries a display image the API has explicitly
    // marked as not this print - so only the other two may be drawn.
    const wrongImage = makePrint({
      card_print_id: 30,
      display_image: {
        url: "https://cdn.example.test/wrong.webp",
        source: "snkrdunk",
        exact_print_verified: false,
        geometry: null,
      },
    });
    fetchPrintCatalogue.mockResolvedValue(
      catalogueResponse([...CATALOGUE.slice(0, 2), wrongImage]),
    );
    const { container } = render(<PrintsCataloguePage />);
    await screen.findAllByRole("link", { name: /Sanji/ });

    const sources = fanImageSources(container);
    expect(sources).toHaveLength(2);
    expect(sources.join(" ")).not.toContain("wrong.webp");
  });

  it("hardcodes no card identity or image URL in the hero fan code", async () => {
    // The composition has to stay a function of the API response. A literal
    // print id, card code or image URL here would pin the fan to particular
    // cards forever, which is the whole thing this rotation exists to undo.
    const sources = [
      readFileSync(resolve(process.cwd(), "src/lib/heroFan.ts"), "utf8"),
      readFileSync(resolve(process.cwd(), "src/components/ui/CatalogueIntro.tsx"), "utf8"),
    ].map(stripComments);

    for (const source of sources) {
      expect(source).not.toMatch(/https?:\/\//);
      // Card codes look like OP01-013 / ST01-001 / EB01-001.
      expect(source).not.toMatch(/\b[A-Z]{2,3}\d{2}-\d{3}\b/);
      expect(source).not.toMatch(/card_?[Pp]rint_?[Ii]d\s*[=:]==?\s*\d/);
      expect(source).not.toMatch(/\.(webp|png|jpe?g)\b/i);
    }
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

/** Clearing a submitted search restores the catalogue on the spot - no second
 * trip to the Search button (tranche 1A). The URL stays the single source of
 * truth: clearing drops `q` and nothing else. */
describe("clearing the catalogue search", () => {
  function clearButton() {
    return screen.getByRole("button", { name: "Clear search" });
  }

  async function renderWith(search: string) {
    currentSearch = search;
    fetchPrintCatalogue.mockResolvedValue(catalogueResponse([SANJI_PARALLEL, SANJI_BASE]));
    const result = render(<PrintsCataloguePage />);
    await screen.findAllByRole("link", { name: /Sanji/ });
    return result;
  }

  it("shows the URL's term in the field, and no clear control without one", async () => {
    await renderWith("");
    expect(screen.getByRole("searchbox")).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Clear search" })).not.toBeInTheDocument();
  });

  it("shows a URL-derived term in the field", async () => {
    await renderWith("q=kaido");
    expect(screen.getByRole("searchbox")).toHaveValue("kaido");
    expect(clearButton()).toBeInTheDocument();
  });

  it("drops q when the clear control is pressed", async () => {
    await renderWith("q=kaido");
    fireEvent.click(clearButton());

    expect(navigations()).toEqual(["/cards"]);
  });

  it("drops q when the last character is deleted", async () => {
    await renderWith("q=k");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "" } });

    expect(navigations()).toEqual(["/cards"]);
  });

  it("drops q on select-all + delete of a longer term", async () => {
    await renderWith("q=kaido");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "" } });

    expect(navigations()).toEqual(["/cards"]);
  });

  it("needs no second submit - the navigation is the restore", async () => {
    await renderWith("q=kaido");
    fireEvent.click(clearButton());

    expect(navigations()).toEqual(["/cards"]);
  });

  it("keeps the treatment filter", async () => {
    await renderWith("q=kaido&treatment=parallel");
    fireEvent.click(clearButton());

    expect(navigations()).toEqual(["/cards?treatment=parallel"]);
  });

  it("keeps the rarity filter", async () => {
    await renderWith("q=kaido&rarity=SR");
    fireEvent.click(clearButton());

    expect(navigations()).toEqual(["/cards?rarity=SR"]);
  });

  it("keeps the sort", async () => {
    await renderWith("q=kaido&sort=index_desc");
    fireEvent.click(clearButton());

    expect(navigations()).toEqual(["/cards?sort=index_desc"]);
  });

  it("keeps every non-q parameter when they are combined", async () => {
    await renderWith("q=kaido&treatment=parallel&rarity=SR&sort=index_desc");
    fireEvent.click(clearButton());

    expect(navigations()).toEqual(["/cards?treatment=parallel&rarity=SR&sort=index_desc"]);
  });

  it("leaves no empty ?q= behind", async () => {
    await renderWith("q=kaido&treatment=parallel&sort=index_desc");
    fireEvent.click(clearButton());

    const [target] = navigations();
    expect(target).not.toMatch(/[?&]q=/);
    expect(target).toBe("/cards?treatment=parallel&sort=index_desc");
  });

  it("re-requests the catalogue without q once the URL has changed", async () => {
    // The page reads its state from the URL, so the restore *is* the
    // navigation - this proves the resulting URL fetches an unfiltered
    // catalogue rather than leaving the filtered response on screen.
    await renderWith("q=kaido&treatment=parallel");
    await waitFor(() =>
      expect(fetchPrintCatalogue).toHaveBeenCalledWith(
        expect.objectContaining({ q: "kaido", treatment: "parallel" }),
      ),
    );

    fireEvent.click(clearButton());
    expect(navigations()).toEqual(["/cards?treatment=parallel"]);

    // What the browser then renders for that URL.
    currentSearch = "treatment=parallel";
    fetchPrintCatalogue.mockClear();
    render(<PrintsCataloguePage />);
    await waitFor(() => expect(fetchPrintCatalogue).toHaveBeenCalled());
    expect(fetchPrintCatalogue).toHaveBeenCalledWith(
      expect.objectContaining({ q: undefined, treatment: "parallel" }),
    );
  });

  it("does not navigate when an unsubmitted draft is cleared", async () => {
    await renderWith("");
    const box = screen.getByRole("searchbox");
    fireEvent.change(box, { target: { value: "kaido" } });
    fireEvent.change(box, { target: { value: "" } });

    // There is no active search to restore from, so clearing is not a
    // navigation - it is just an empty box.
    expect(navigations()).toEqual([]);
  });

  it("follows the URL when a back navigation changes the committed term", async () => {
    const { rerender } = await renderWith("q=kaido");
    const box = screen.getByRole("searchbox");
    expect(box).toHaveValue("kaido");

    // A typed-but-unsubmitted draft is what a browser Back has to overrule:
    // the URL, not the box, is the source of truth for `q`.
    fireEvent.change(box, { target: { value: "kaid" } });
    currentSearch = "q=sanji";
    rerender(<PrintsCataloguePage />);

    expect(screen.getByRole("searchbox")).toHaveValue("sanji");
  });

  it("leaves typing alone on a re-render that did not change the term", async () => {
    const { rerender } = await renderWith("q=kaido");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "kaido parallel" } });

    rerender(<PrintsCataloguePage />);

    expect(screen.getByRole("searchbox")).toHaveValue("kaido parallel");
  });
});

/** Pagination as the collector meets it: 179 pages of catalogue, and the way
 * onward has to be visible under the grid rather than read as footer text.
 * Presentation is asserted in PaginationControls.test.tsx; what matters here
 * is that /cards asks for the catalogue presentation and that paging still
 * goes through the URL exactly as it did. */
describe("catalogue pagination", () => {
  /** A response that really is one page of a much longer catalogue. The
   * shared `catalogueResponse` sets total = items.length, which is a single
   * page by definition and hides the controls. */
  function pageOf(items: PrintCatalogueItem[], offset: number, total: number): PrintCatalogueList {
    const base = catalogueResponse(items);
    return {
      ...base,
      total,
      offset,
      pagination: {
        ...base.pagination,
        total,
        offset,
        has_next: offset + 24 < total,
        has_previous: offset > 0,
        next_offset: offset + 24 < total ? offset + 24 : null,
        previous_offset: offset > 0 ? Math.max(0, offset - 24) : null,
      },
    };
  }

  async function renderPage(offset: number, total = 4281) {
    currentSearch = offset > 0 ? `offset=${offset}` : "";
    fetchPrintCatalogue.mockResolvedValue(pageOf(CATALOGUE, offset, total));
    const view = render(<PrintsCataloguePage />);
    await waitFor(() => expect(screen.getByRole("navigation", { name: "Catalogue pagination" })).toBeInTheDocument());
    return view;
  }

  it("renders the catalogue pagination landmark under the grid, not the dense bar", async () => {
    await renderPage(0);
    const nav = screen.getByRole("navigation", { name: "Catalogue pagination" });
    expect(nav.className).toContain("border-t");
    expect(within(nav).getByText("Page 1 of 179")).toBeInTheDocument();
    expect(within(nav).getByText("Showing 1–24 of 4,281")).toBeInTheDocument();
  });

  it("disables Previous on the first page", async () => {
    await renderPage(0);
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).not.toBeDisabled();
  });

  it("enables both controls in the middle of the catalogue", async () => {
    await renderPage(2160);
    expect(screen.getByRole("button", { name: "Previous" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).not.toBeDisabled();
    expect(screen.getByText("Page 91 of 179")).toBeInTheDocument();
  });

  it("disables Next on the last page", async () => {
    await renderPage(4272);
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous" })).not.toBeDisabled();
    expect(screen.getByText("Page 179 of 179")).toBeInTheDocument();
  });

  it("commits the next page to the URL as ?offset=, unchanged", async () => {
    await renderPage(0);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(navigations().at(-1)).toBe("/cards?offset=24");
  });

  it("drops ?offset= entirely on the way back to page one", async () => {
    await renderPage(24);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(navigations().at(-1)).toBe("/cards");
  });

  it("still honours an offset that arrived in the URL", async () => {
    await renderPage(96);
    expect(fetchPrintCatalogue).toHaveBeenCalledWith(
      expect.objectContaining({ offset: 96, limit: 24 }),
    );
    expect(screen.getByText("Page 5 of 179")).toBeInTheDocument();
  });

  it("keeps the grid to one tile per print, untouched by the pagination change", async () => {
    await renderPage(0);
    expect(screen.getAllByRole("link", { name: /OP0/ })).toHaveLength(CATALOGUE.length);
  });
});
