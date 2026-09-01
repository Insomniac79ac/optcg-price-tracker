/** The canonical family route: one card code, every printing, no guessing.
 *
 * The claims that matter here are the refusals - it must not choose a
 * printing, must not price the family, must not name a card its own records
 * disagree about, and must not touch anything private.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));

let routeParams: Record<string, string> = { cardCode: "OP04-044" };
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/cards/code/OP04-044",
  useParams: () => routeParams,
}));

const fetchPrintCatalogue = vi.fn();
vi.mock("@/lib/prints", async () => {
  const actual = await vi.importActual<typeof import("@/lib/prints")>("@/lib/prints");
  return { ...actual, fetchPrintCatalogue: (...args: unknown[]) => fetchPrintCatalogue(...args) };
});

const CardFamilyPage = (await import("./page")).default;

function printItem(overrides: Record<string, unknown> = {}) {
  return {
    card_print_id: 13,
    canonical_card_id: 10,
    card_code: "OP04-044",
    name_en: "Kaido",
    name_jp: "カイドウ",
    rarity: "SR",
    canonical_rarity: "SR",
    card_type: "Character",
    treatment: "parallel",
    language: "jp",
    release_product_code: "OP-04",
    original_set_code: "OP-04",
    official_asset_variant: "p1",
    image_url: "https://example.test/13.png",
    display_image: null,
    verification_status: "verified",
    source_coverage: [],
    latest_observation_at: null,
    market_index: {
      card_print_id: 13,
      index_version: 1,
      index_value_jpy: 1040,
      calculation_method: "midpoint",
      source_count: 2,
      coverage_status: "full",
      confidence: "high",
      source_values: [],
      auxiliary_values: [],
      freshest_observation_at: null,
      stalest_eligible_source_at: null,
      stale_sources: [],
      calculated_at: "2026-09-01T00:00:00Z",
    },
    ...overrides,
  };
}

function mockCatalogue(items: unknown[]) {
  fetchPrintCatalogue.mockResolvedValue({
    items,
    total: items.length,
    limit: 100,
    offset: 0,
    pagination: {},
    facets: { treatments: [], rarities: [], languages: [], verification_statuses: [] },
  });
}

const BASE = printItem({ card_print_id: 14, treatment: "normal", official_asset_variant: "base" });
const ALT = printItem();
const UNPRICED = printItem({
  card_print_id: 2967,
  treatment: null,
  official_asset_variant: null,
  market_index: { ...printItem().market_index, card_print_id: 2967, index_value_jpy: null, source_count: 0, coverage_status: "none", confidence: "low" },
});

function printLinks() {
  return screen.getAllByRole("link").filter((l) => l.getAttribute("href")?.startsWith("/prints/"));
}

beforeEach(() => {
  vi.clearAllMocks();
  routeParams = { cardCode: "OP04-044" };
});

describe("A. multi-print family", () => {
  it("shows the canonical name, the code, and every printing", async () => {
    mockCatalogue([BASE, ALT, UNPRICED]);
    render(<CardFamilyPage />);

    await waitFor(() => expect(printLinks()).toHaveLength(3));

    expect(screen.getByRole("heading", { level: 1, name: "Kaido" })).toBeInTheDocument();
    expect(screen.getAllByText("OP04-044").length).toBeGreaterThan(0);
    expect(
      screen.getByRole("heading", { name: /Printings of Kaido OP04-044/ }),
    ).toBeInTheDocument();
    expect(printLinks().map((l) => l.getAttribute("href")).sort()).toEqual([
      "/prints/14",
      "/prints/2967",
      "/prints/13",
    ].sort());
  });

  it("J. links only to exact prints - never a legacy card id", async () => {
    mockCatalogue([BASE, ALT]);
    render(<CardFamilyPage />);
    await waitFor(() => expect(printLinks()).toHaveLength(2));

    for (const l of screen.getAllByRole("link")) {
      const href = l.getAttribute("href") ?? "";
      expect(href).not.toMatch(/^\/cards\/\d+$/);
    }
  });

  it("N. keeps an unpriced printing honest", async () => {
    mockCatalogue([BASE, UNPRICED]);
    render(<CardFamilyPage />);
    await waitFor(() => expect(printLinks()).toHaveLength(2));

    expect(screen.getByText(/Index unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText("￥0")).not.toBeInTheDocument();
  });

  it("M. every tile's artwork stays uncropped", async () => {
    mockCatalogue([BASE, ALT]);
    const { container } = render(<CardFamilyPage />);
    await waitFor(() => expect(printLinks()).toHaveLength(2));

    // Scoped to the printing tiles: the app header has its own logo images.
    const imgs = [...container.querySelectorAll('a[href^="/prints/"] img')];
    expect(imgs.length).toBeGreaterThanOrEqual(2);
    for (const img of imgs) {
      expect(img.className).toContain("object-contain");
      expect(img.className).not.toContain("object-cover");
    }
  });

  it("states no family-level price, rarity or variant", async () => {
    mockCatalogue([BASE, ALT, UNPRICED]);
    const { container } = render(<CardFamilyPage />);
    await waitFor(() => expect(printLinks()).toHaveLength(3));

    // The only ¥ figures on the page belong to individual tiles.
    const yen = (container.textContent ?? "").match(/￥[\d,]+/g) ?? [];
    expect(yen).toEqual(["￥1,040", "￥1,040"]);
    expect(container.querySelector("main table")).toBeNull();
    // Each tile carries its own chips; this page's own header carries none.
    // Scoped inside the article - the app header is a different <header>.
    const header = container.querySelector("article header");
    expect(header?.textContent).toContain("Kaido");
    expect(header?.textContent).toContain("OP04-044");
    expect(header?.textContent).not.toMatch(/Super Rare|Alt Art|parallel/);
  });
});

describe("B. single-print family", () => {
  it("renders one option and still names the section", async () => {
    mockCatalogue([BASE]);
    render(<CardFamilyPage />);
    await waitFor(() => expect(printLinks()).toHaveLength(1));

    expect(printLinks()[0]).toHaveAttribute("href", "/prints/14");
    expect(screen.getByRole("heading", { name: /Printings of/ })).toBeInTheDocument();
  });
});

describe("exact-code filtering", () => {
  it("drops another card's printing returned by the substring search", async () => {
    // `q` is a substring ILIKE, so a code query can match a longer code.
    mockCatalogue([
      BASE,
      printItem({ card_print_id: 999, canonical_card_id: 77, card_code: "OP04-0440" }),
    ]);
    render(<CardFamilyPage />);
    await waitFor(() => expect(printLinks()).toHaveLength(1));

    expect(printLinks()[0]).toHaveAttribute("href", "/prints/14");
    expect(fetchPrintCatalogue).toHaveBeenCalledWith({ q: "OP04-044", limit: 100 });
  });

  it("G. renders the not-found state when no printing carries the code", async () => {
    mockCatalogue([printItem({ card_print_id: 999, canonical_card_id: 77, card_code: "OP04-0440" })]);
    render(<CardFamilyPage />);

    await waitFor(() =>
      expect(screen.getByText(/isn’t in the Atlas/)).toBeInTheDocument(),
    );
    expect(printLinks()).toHaveLength(0);
    expect(screen.queryByRole("heading", { name: /Printings of/ })).not.toBeInTheDocument();
  });
});

describe("I. canonical disagreement fails closed", () => {
  it("shows no printings when the records name two different canonical cards", async () => {
    mockCatalogue([BASE, printItem({ card_print_id: 500, canonical_card_id: 999 })]);
    render(<CardFamilyPage />);

    await waitFor(() => expect(screen.getByText(/can’t be shown yet/)).toBeInTheDocument());
    // Fail closed means the printings are withheld, not listed under a guess.
    expect(printLinks()).toHaveLength(0);
    expect(screen.queryByRole("heading", { level: 1, name: "Kaido" })).not.toBeInTheDocument();
  });

  it("shows no printings when the records disagree on the name", async () => {
    mockCatalogue([BASE, printItem({ card_print_id: 501, name_en: "Kaidou" })]);
    render(<CardFamilyPage />);

    await waitFor(() => expect(screen.getByText(/don’t agree on which card it is/)).toBeInTheDocument());
    expect(printLinks()).toHaveLength(0);
    // Neither spelling is elected.
    expect(screen.queryByText("Kaidou")).not.toBeInTheDocument();
  });
});

describe("K. the legacy cards table cannot reach this route", () => {
  it("asks the catalogue by card code and nothing else", async () => {
    mockCatalogue([BASE]);
    render(<CardFamilyPage />);
    await waitFor(() => expect(printLinks()).toHaveLength(1));

    expect(fetchPrintCatalogue).toHaveBeenCalledTimes(1);
    expect(fetchPrintCatalogue).toHaveBeenCalledWith({ q: "OP04-044", limit: 100 });
  });

  it("a corrupt legacy row for the same code cannot change what is shown", async () => {
    // Staging legacy row 1 is card_code OP01-001 named "Monkey D. Luffy" while
    // canonically OP01-001 is Roronoa Zoro. This route never reads that table,
    // so the canonical record is simply what renders.
    routeParams = { cardCode: "OP01-001" };
    mockCatalogue([
      printItem({ card_print_id: 1, canonical_card_id: 7, card_code: "OP01-001", name_en: "Roronoa Zoro", name_jp: "ロロノア・ゾロ" }),
    ]);
    render(<CardFamilyPage />);
    await waitFor(() => expect(printLinks()).toHaveLength(1));

    expect(screen.getByRole("heading", { level: 1, name: "Roronoa Zoro" })).toBeInTheDocument();
    expect(screen.queryByText(/Monkey D\. Luffy/)).not.toBeInTheDocument();
  });
});

describe("L. the public family route is public", () => {
  it("renders anonymously and requests nothing private", async () => {
    mockCatalogue([BASE, ALT]);
    render(<CardFamilyPage />);
    await waitFor(() => expect(printLinks()).toHaveLength(2));

    // No ownership/wishlist/grading/tags/notes surface exists on this route.
    for (const text of [
      "Not in collection yet.",
      "Not on wishlist.",
      "No grading submissions.",
      "Card tags",
      "No notes yet.",
      "Source mappings (admin)",
    ]) {
      expect(screen.queryByText(text), text).not.toBeInTheDocument();
    }
    // The catalogue is the only thing this page asks for.
    expect(fetchPrintCatalogue).toHaveBeenCalledTimes(1);
  });

  it("keeps each printing's own identifying detail on its own tile", async () => {
    mockCatalogue([BASE, ALT]);
    render(<CardFamilyPage />);
    await waitFor(() => expect(printLinks()).toHaveLength(2));

    for (const link of printLinks()) {
      expect(within(link).getAllByText("OP04-044").length).toBeGreaterThan(0);
    }
    // The two options must not read identically.
    expect(new Set(printLinks().map((l) => l.getAttribute("aria-label"))).size).toBe(2);
  });
});
