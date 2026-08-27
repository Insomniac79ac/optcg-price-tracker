/**
 * Frontend readiness for a future `treatment: null` on a printing.
 *
 * null means Atlas has not classified that printing. The contract is: no
 * badge, no "Unclassified" text, no invented fallback label - and the rest of
 * the print's identity renders exactly as it does today. Today's normal and
 * parallel printings must be untouched by any of this.
 */
import { describe, expect, it } from "vitest";

import { toPrintUiModel, type PrintCatalogueItem, type PrintMarketIndex } from "@/lib/prints";
import { printToPaletteResult } from "@/lib/publicCardSearch";

function marketIndex(): PrintMarketIndex {
  return {
    card_print_id: 3,
    index_value_jpy: 1740,
    calculation_method: "median_of_sources",
    source_count: 2,
    coverage_status: "full",
    confidence: "high",
    index_version: 1,
    source_semantics_version: 1,
    source_price_range: { low_jpy: 1500, high_jpy: 1980 },
    source_values: [],
    auxiliary_values: [],
    freshest_observation_at: null,
    stalest_eligible_source_at: null,
    stale_sources: [],
    calculated_at: "2026-08-21T20:04:58.406986Z",
  };
}

function item(overrides: Partial<PrintCatalogueItem> = {}): PrintCatalogueItem {
  return {
    card_print_id: 3,
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
    image_url: "https://example.test/OP01-013_p2.png",
    display_image: null,
    verification_status: "verified",
    market_index: marketIndex(),
    source_coverage: ["yuyutei"],
    latest_observation_at: null,
    ...overrides,
  };
}

describe("toPrintUiModel with a null treatment", () => {
  it("does not throw", () => {
    expect(() => toPrintUiModel(item({ treatment: null }))).not.toThrow();
  });

  it("carries the null through rather than inventing a label", () => {
    const model = toPrintUiModel(item({ treatment: null }));

    expect(model.treatment).toBeNull();
    expect(model.isDistinctTreatment).toBe(false);
  });

  it("still renders the rest of the print's identity", () => {
    const model = toPrintUiModel(item({ treatment: null }));

    expect(model.cardCode).toBe("OP01-013");
    expect(model.displayName).toBe("Sanji");
    expect(model.rarity).toBe("R");
    expect(model.releaseCode).toBe("OP-01");
    expect(model.imageUrl).toBe("https://example.test/OP01-013_p2.png");
    expect(model.marketIndex.index_value_jpy).toBe(1740);
  });

  it("leaves classified printings exactly as they were", () => {
    expect(toPrintUiModel(item({ treatment: "parallel" })).isDistinctTreatment).toBe(true);
    expect(toPrintUiModel(item({ treatment: "normal" })).isDistinctTreatment).toBe(false);
    expect(toPrintUiModel(item({ treatment: "normal" })).treatment).toBe("normal");
  });
});

describe("search palette subtitle with a null treatment", () => {
  it("omits the treatment segment entirely", () => {
    const result = printToPaletteResult(item({ treatment: null }));

    expect(result.subtitle).toBe("OP01-013 · OP-01");
    expect(result.subtitle).not.toMatch(/null|undefined|unclassified|unknown/i);
  });

  it("still names a distinct treatment when there is one", () => {
    expect(printToPaletteResult(item({ treatment: "parallel" })).subtitle).toBe(
      "OP01-013 · OP-01 · parallel",
    );
    expect(printToPaletteResult(item({ treatment: "normal" })).subtitle).toBe("OP01-013 · OP-01");
  });
});
