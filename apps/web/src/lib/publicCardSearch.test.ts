import { describe, expect, it, vi } from "vitest";

const fetchPrintCatalogue = vi.fn();
vi.mock("./prints", async () => {
  const actual = await vi.importActual<typeof import("./prints")>("./prints");
  return { ...actual, fetchPrintCatalogue: (...args: unknown[]) => fetchPrintCatalogue(...args) };
});

const {
  printToPaletteResult,
  searchPublicPrints,
  PUBLIC_CARD_SEARCH_LIMIT,
  groupPrintsIntoFamilies,
  familyToPaletteResult,
  searchPublicCardFamilies,
  familyRouteFor,
} = await import("./publicCardSearch");

function printItem(overrides: Record<string, unknown> = {}) {
  return {
    card_print_id: 13,
    canonical_card_id: 40,
    card_code: "OP04-044",
    name_en: "Kaido",
    name_jp: "カイドウ",
    rarity: "SR",
    card_type: "Character",
    treatment: "parallel",
    language: "jp",
    release_product_code: "OP-04",
    original_set_code: "OP-04",
    official_asset_variant: "base",
    image_url: null,
    display_image: null,
    verification_status: "verified",
    source_coverage: [],
    latest_observation_at: null,
    market_index: {
      card_print_id: 13,
      index_version: 1,
      index_value_jpy: 1040,
      calculation_method: "median",
      source_count: 1,
      coverage_status: "limited",
      confidence: "medium",
      source_values: [],
      auxiliary_values: [],
      freshest_observation_at: null,
      stalest_eligible_source_at: null,
      stale_sources: [],
      calculated_at: "2026-08-18T00:00:00Z",
    },
    ...overrides,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;
}

describe("printToPaletteResult", () => {
  it("links to the print, never the canonical card id", () => {
    const result = printToPaletteResult(printItem({ card_print_id: 13, canonical_card_id: 40 }));
    expect(result.url).toBe("/prints/13");
    expect(result.url).not.toContain("/cards/");
    expect(result.url).not.toContain("40");
  });

  it("titles the row with the card's display name", () => {
    expect(printToPaletteResult(printItem()).title).toBe("Kaido");
  });

  it("falls back to the Japanese name, then the code, when English is absent", () => {
    expect(printToPaletteResult(printItem({ name_en: null })).title).toBe("カイドウ");
    expect(printToPaletteResult(printItem({ name_en: null, name_jp: null })).title).toBe(
      "OP04-044",
    );
  });

  it("names the treatment only when it is one worth naming", () => {
    expect(printToPaletteResult(printItem({ treatment: "parallel" })).subtitle).toBe(
      "OP04-044 · OP-04 · parallel",
    );
    expect(printToPaletteResult(printItem({ treatment: "normal" })).subtitle).toBe(
      "OP04-044 · OP-04",
    );
  });

  it("keeps sibling printings of one card distinguishable", () => {
    const parallel = printToPaletteResult(printItem({ card_print_id: 13, treatment: "parallel" }));
    const base = printToPaletteResult(printItem({ card_print_id: 14, treatment: "normal" }));
    expect(parallel.subtitle).not.toBe(base.subtitle);
    expect(parallel.url).not.toBe(base.url);
    expect(parallel.key).not.toBe(base.key);
  });
});

describe("searchPublicPrints", () => {
  it("issues one request against the public catalogue", async () => {
    fetchPrintCatalogue.mockReset().mockResolvedValue({ items: [printItem()] });
    const results = await searchPublicPrints("kaido");
    expect(fetchPrintCatalogue).toHaveBeenCalledTimes(1);
    expect(fetchPrintCatalogue).toHaveBeenCalledWith({ q: "kaido", limit: PUBLIC_CARD_SEARCH_LIMIT });
    expect(results.map((r) => r.url)).toEqual(["/prints/13"]);
  });

  it("resolves empty for a genuine zero-result search", async () => {
    fetchPrintCatalogue.mockReset().mockResolvedValue({ items: [] });
    await expect(searchPublicPrints("zzzznotacard")).resolves.toEqual([]);
  });

  it("rejects on failure rather than resolving empty", async () => {
    // An empty resolve would be indistinguishable from "no such card".
    fetchPrintCatalogue.mockReset().mockRejectedValue(new Error("network down"));
    await expect(searchPublicPrints("kaido")).rejects.toThrow("network down");
  });
});

// ---------------------------------------------------------------------------
// Canonical family search
// ---------------------------------------------------------------------------

/** OP04-044 Kaido: one canonical card, five printings - the shape that made
 * print-level results list one card five times. */
const KAIDO = [
  printItem({ card_print_id: 14, canonical_card_id: 10, treatment: "normal" }),
  printItem({ card_print_id: 13, canonical_card_id: 10 }),
  printItem({ card_print_id: 2967, canonical_card_id: 10, treatment: null }),
  printItem({ card_print_id: 2968, canonical_card_id: 10, treatment: null }),
  printItem({ card_print_id: 5550, canonical_card_id: 10, treatment: null }),
];

const VIVI_SINGLE = printItem({
  card_print_id: 5686,
  canonical_card_id: 9,
  card_code: "OP04-118",
  name_en: "Nefeltari Vivi",
  name_jp: "ネフェルタリ・ビビ",
});

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

describe("A/H. canonical family grouping", () => {
  it("collapses a five-printing card into ONE family result", () => {
    const families = groupPrintsIntoFamilies(KAIDO);

    expect(families).toHaveLength(1);
    expect(families[0]).toMatchObject({
      cardCode: "OP04-044",
      name: "Kaido",
      printingCount: 5,
      url: "/cards/code/OP04-044",
    });
  });

  it("says how many printings are waiting, but only when there is a choice", () => {
    expect(familyToPaletteResult(groupPrintsIntoFamilies(KAIDO)[0]).subtitle).toBe(
      "OP04-044 · 5 printings",
    );
    // B. a single-printing family states no count - there is nothing to choose.
    expect(familyToPaletteResult(groupPrintsIntoFamilies([VIVI_SINGLE])[0]).subtitle).toBe(
      "OP04-118",
    );
  });

  it("groups by canonical id, so two different cards never merge", () => {
    const families = groupPrintsIntoFamilies([...KAIDO, VIVI_SINGLE]);
    expect(families.map((f) => f.cardCode)).toEqual(["OP04-044", "OP04-118"]);
    expect(families.map((f) => f.printingCount)).toEqual([5, 1]);
  });

  it("keeps the catalogue's order and truncates families, not prints", () => {
    const many = [
      ...KAIDO,
      printItem({ card_print_id: 1, canonical_card_id: 11, card_code: "OP04-045" }),
      printItem({ card_print_id: 2, canonical_card_id: 12, card_code: "OP04-046" }),
    ];
    expect(groupPrintsIntoFamilies(many, 2).map((f) => f.cardCode)).toEqual([
      "OP04-044",
      "OP04-045",
    ]);
  });
});

describe("I. a family whose records disagree is never given a guessed name", () => {
  it("falls back to the card code rather than picking one spelling", () => {
    const disagreeing = [
      printItem({ card_print_id: 1, canonical_card_id: 10, name_en: "Kaido" }),
      printItem({ card_print_id: 2, canonical_card_id: 10, name_en: "Kaidou" }),
    ];
    const [family] = groupPrintsIntoFamilies(disagreeing);

    expect(family.name).toBeNull();
    expect(family.printingCount).toBe(2);
    // Still findable, still one row, still addressed by the code both records
    // agree on - and titled by that code, never by a chosen name.
    expect(familyToPaletteResult(family).title).toBe("OP04-044");
    expect(familyToPaletteResult(family).url).toBe("/cards/code/OP04-044");
  });
});

describe("J/K. family results never point at a print or a legacy card", () => {
  it("links only to the canonical family route", async () => {
    mockCatalogue(KAIDO);
    const results = await searchPublicCardFamilies("kaido");

    expect(results).toHaveLength(1);
    expect(results[0].url).toBe("/cards/code/OP04-044");
    expect(results[0].url.startsWith("/prints/")).toBe(false);
    expect(results[0].url.startsWith("/cards/")).toBe(true);
    // K. the only id in the URL is the published card code - no legacy
    // `cards`.id and no canonical id.
    expect(results[0].url).not.toMatch(/\/cards\/\d+$/);
  });

  it("percent-encodes a code so it can never break the route", () => {
    expect(familyRouteFor("OP04-044")).toBe("/cards/code/OP04-044");
    expect(familyRouteFor("A B/C")).toBe("/cards/code/A%20B%2FC");
  });
});

describe("C-G. query shapes reach the public catalogue unchanged", () => {
  it.each([
    ["C. exact code", "OP04-044"],
    ["D. partial code", "OP04-0"],
    ["E. English name", "Kaido"],
    ["F. Japanese name", "カイドウ"],
  ])("%s is passed through to GET /prints", async (_label, query) => {
    mockCatalogue(KAIDO);
    await searchPublicCardFamilies(query);
    expect(fetchPrintCatalogue).toHaveBeenCalledWith({ q: query, limit: 100 });
  });

  it("G. an empty catalogue answer yields no families rather than throwing", async () => {
    mockCatalogue([]);
    await expect(searchPublicCardFamilies("zzzznotacard")).resolves.toEqual([]);
  });

  it("returns at most PUBLIC_CARD_SEARCH_LIMIT families", async () => {
    mockCatalogue(
      Array.from({ length: 30 }, (_, i) =>
        printItem({ card_print_id: i, canonical_card_id: 1000 + i, card_code: `OP99-${i}` }),
      ),
    );
    const results = await searchPublicCardFamilies("op99");
    expect(results).toHaveLength(PUBLIC_CARD_SEARCH_LIMIT);
  });
});
