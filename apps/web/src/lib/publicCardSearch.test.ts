import { describe, expect, it, vi } from "vitest";

const fetchPrintCatalogue = vi.fn();
vi.mock("./prints", async () => {
  const actual = await vi.importActual<typeof import("./prints")>("./prints");
  return { ...actual, fetchPrintCatalogue: (...args: unknown[]) => fetchPrintCatalogue(...args) };
});

const { printToPaletteResult, searchPublicPrints, PUBLIC_CARD_SEARCH_LIMIT } = await import(
  "./publicCardSearch"
);

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
