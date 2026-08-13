import { describe, expect, it } from "vitest";

import {
  toPrintUiModel,
  sourceDisplayName,
  type PrintCatalogueItem,
  type PrintMarketIndex,
  type PrintMarketIndexSourceValue,
} from "./prints";

function sourceValue(
  overrides: Partial<PrintMarketIndexSourceValue> & { source: string },
): PrintMarketIndexSourceValue {
  return {
    reference_type: "retail_sell",
    evidence_type: "listing",
    value_jpy: null,
    observed_at: null,
    sample_size: null,
    stale: false,
    eligible: true,
    fallback_used: false,
    ineligible_reason: null,
    ...overrides,
  };
}

function marketIndex(overrides: Partial<PrintMarketIndex> = {}): PrintMarketIndex {
  return {
    card_print_id: 3,
    index_version: 1,
    index_value_jpy: 1740,
    calculation_method: "median_of_sources",
    source_count: 2,
    coverage_status: "full",
    confidence: "high",
    source_values: [
      sourceValue({ source: "yuyutei", value_jpy: 1980 }),
      sourceValue({ source: "snkrdunk", reference_type: "listing_floor", value_jpy: 1500 }),
    ],
    auxiliary_values: [],
    freshest_observation_at: "2026-08-11T19:21:25.989165Z",
    stalest_eligible_source_at: "2026-08-11T18:20:37.385148Z",
    stale_sources: [],
    calculated_at: "2026-08-12T13:45:05.031460Z",
    ...overrides,
  };
}

function catalogueItem(
  overrides: Partial<PrintCatalogueItem> = {},
): PrintCatalogueItem {
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
    image_url: "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-013_p2.png",
    display_image: null,
    verification_status: "verified",
    market_index: marketIndex(),
    source_coverage: ["snkrdunk", "yuyutei"],
    latest_observation_at: "2026-08-11T19:21:25.989165Z",
    ...overrides,
  };
}

describe("toPrintUiModel", () => {
  it("keys the model by card_print_id and carries no legacy card_id", () => {
    const model = toPrintUiModel(catalogueItem());

    expect(model.cardPrintId).toBe(3);
    expect(Object.keys(model)).not.toContain("cardId");
    expect(Object.keys(model)).not.toContain("card_id");
    expect(JSON.stringify(model)).not.toContain("card_id");
  });

  it("reads each source price out of this print's own market index", () => {
    const model = toPrintUiModel(catalogueItem());

    expect(model.marketIndexJpy).toBe(1740);
    expect(model.yuyuteiJpy).toBe(1980);
    expect(model.snkrdunkJpy).toBe(1500);
    expect(model.contributingSources).toEqual(["Yuyu-Tei", "SNKRDUNK"]);
  });

  it("keeps sibling prints independent - the base print resolves its own values", () => {
    // Sanji OP01-013 base: same card_code and same legacy card as the
    // parallel above, but only Yuyu-Tei has a price for it.
    const base = toPrintUiModel(
      catalogueItem({
        card_print_id: 4,
        treatment: "normal",
        market_index: marketIndex({
          card_print_id: 4,
          index_value_jpy: 120,
          source_count: 1,
          coverage_status: "limited",
          confidence: "medium",
          source_values: [
            sourceValue({ source: "yuyutei", value_jpy: 120 }),
            sourceValue({ source: "snkrdunk", reference_type: "listing_floor", value_jpy: null }),
          ],
        }),
      }),
    );
    const parallel = toPrintUiModel(catalogueItem());

    expect(base.cardPrintId).not.toBe(parallel.cardPrintId);
    expect(base.cardCode).toBe(parallel.cardCode);
    expect(base.marketIndexJpy).toBe(120);
    expect(parallel.marketIndexJpy).toBe(1740);
    expect(base.snkrdunkJpy).toBeNull();
    expect(base.contributingSources).toEqual(["Yuyu-Tei"]);
  });

  it("flags a distinct treatment but not the plain base printing", () => {
    expect(toPrintUiModel(catalogueItem({ treatment: "parallel" })).isDistinctTreatment).toBe(
      true,
    );
    expect(toPrintUiModel(catalogueItem({ treatment: "normal" })).isDistinctTreatment).toBe(
      false,
    );
  });

  it("falls back from English to Japanese to the card code for a display name", () => {
    expect(toPrintUiModel(catalogueItem()).displayName).toBe("Sanji");
    expect(toPrintUiModel(catalogueItem({ name_en: null })).displayName).toBe("サンジ");
    expect(
      toPrintUiModel(catalogueItem({ name_en: null, name_jp: null })).displayName,
    ).toBe("OP01-013");
  });

  it("never invents a price when the index is unavailable", () => {
    const model = toPrintUiModel(
      catalogueItem({
        market_index: marketIndex({
          index_value_jpy: null,
          source_count: 0,
          coverage_status: "none",
          source_values: [],
        }),
      }),
    );

    expect(model.marketIndexJpy).toBeNull();
    expect(model.yuyuteiJpy).toBeNull();
    expect(model.snkrdunkJpy).toBeNull();
    expect(model.contributingSources).toEqual([]);
  });
});

describe("sourceDisplayName", () => {
  it("maps API source names to collector-facing names", () => {
    expect(sourceDisplayName("yuyutei")).toBe("Yuyu-Tei");
    expect(sourceDisplayName("snkrdunk")).toBe("SNKRDUNK");
  });

  it("passes an unknown source through rather than inventing a label", () => {
    expect(sourceDisplayName("cardrush")).toBe("cardrush");
  });
});

describe("toPrintUiModel display image selection", () => {
  const BANDAI = "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-013_p2.png";
  const SNKR = "https://cdn.snkrdunk.com/upload_bg_removed/TCG-OPC-OP01-0001.webp?size=l";

  it("renders the verified SNKRDUNK display image, hotlinked not proxied", () => {
    const model = toPrintUiModel(
      catalogueItem({
        display_image: { url: SNKR, source: "snkrdunk", exact_print_verified: true },
      }),
    );

    expect(model.imageUrl).toBe(SNKR);
    expect(model.imageSource).toBe("snkrdunk");
  });

  it("keeps canonical image_url as identity evidence, not as what is rendered", () => {
    const model = toPrintUiModel(
      catalogueItem({
        display_image: { url: SNKR, source: "snkrdunk", exact_print_verified: true },
      }),
    );

    expect(model.sourceImageUrl).toBe(BANDAI);
    expect(model.sourceImageUrl).not.toBe(model.imageUrl);
  });

  it("falls back to the proxied canonical Bandai image when the source is bandai", () => {
    const model = toPrintUiModel(
      catalogueItem({
        display_image: { url: BANDAI, source: "bandai", exact_print_verified: true },
      }),
    );

    // Bandai sends CORP: same-site, so it must go through the same-origin proxy.
    expect(model.imageUrl).toContain("/api/card-image?u=");
    expect(model.imageSource).toBe("bandai");
  });

  it("falls back to the canonical image when the API omits display_image entirely", () => {
    const model = toPrintUiModel(catalogueItem({ display_image: null }));

    expect(model.imageUrl).toContain("/api/card-image?u=");
    expect(model.imageSource).toBeNull();
  });

  it("never lets a sibling's display image reach this print", () => {
    const parallel = toPrintUiModel(
      catalogueItem({
        card_print_id: 3,
        display_image: { url: SNKR, source: "snkrdunk", exact_print_verified: true },
      }),
    );
    const base = toPrintUiModel(
      catalogueItem({ card_print_id: 4, treatment: "normal", display_image: null }),
    );

    expect(parallel.imageUrl).toBe(SNKR);
    expect(base.imageUrl).not.toBe(SNKR);
    expect(base.imageUrl).toContain("/api/card-image?u=");
  });
});
