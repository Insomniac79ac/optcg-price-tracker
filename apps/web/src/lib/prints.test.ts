import { describe, expect, it } from "vitest";

import {
  printsNeedingArtOrdinal,
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
    canonical_rarity: "R",
    card_type: "Character",
    treatment: "parallel",
    language: "jp",
    release_product_code: "OP-01",
    original_set_code: "OP-01",
    official_asset_variant: "base",
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
        display_image: { url: SNKR, source: "snkrdunk", exact_print_verified: true, geometry: null },
      }),
    );

    expect(model.imageUrl).toBe(SNKR);
    expect(model.imageSource).toBe("snkrdunk");
  });

  it("keeps canonical image_url as identity evidence, not as what is rendered", () => {
    const model = toPrintUiModel(
      catalogueItem({
        display_image: { url: SNKR, source: "snkrdunk", exact_print_verified: true, geometry: null },
      }),
    );

    expect(model.sourceImageUrl).toBe(BANDAI);
    expect(model.sourceImageUrl).not.toBe(model.imageUrl);
  });

  it("falls back to the proxied canonical Bandai image when the source is bandai", () => {
    const model = toPrintUiModel(
      catalogueItem({
        display_image: { url: BANDAI, source: "bandai", exact_print_verified: true, geometry: null },
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
        display_image: { url: SNKR, source: "snkrdunk", exact_print_verified: true, geometry: null },
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

describe("toPrintUiModel display geometry", () => {
  const SNKR = "https://cdn.snkrdunk.com/upload_bg_removed/TCG-OPC-OP01-0001.webp?size=l";
  const GEOMETRY = {
    canvas_px: { width: 856, height: 625 },
    card_bbox_px: { x: 241, y: 51, width: 374, height: 523 },
  };

  it("passes verified geometry through to the UI model", () => {
    const model = toPrintUiModel(
      catalogueItem({
        display_image: {
          url: SNKR,
          source: "snkrdunk",
          exact_print_verified: true,
          geometry: GEOMETRY,
        },
      }),
    );

    expect(model.imageGeometry).toEqual(GEOMETRY);
  });

  it("carries no geometry for a Bandai fallback", () => {
    const model = toPrintUiModel(
      catalogueItem({
        display_image: {
          url: "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-013_p2.png",
          source: "bandai",
          exact_print_verified: true,
          geometry: null,
        },
      }),
    );

    expect(model.imageGeometry).toBeNull();
  });

  it("carries no geometry when the API omits display_image entirely", () => {
    expect(toPrintUiModel(catalogueItem({ display_image: null })).imageGeometry).toBeNull();
  });

  it("never attaches geometry to a canonical URL it did not describe", () => {
    // A display_image with geometry but no url must not leak its box onto the
    // canonical image we fall back to.
    const model = toPrintUiModel(
      catalogueItem({
        display_image: {
          url: "",
          source: "snkrdunk",
          exact_print_verified: true,
          geometry: GEOMETRY,
        },
      }),
    );

    expect(model.imageUrl).toContain("/api/card-image?u=");
    expect(model.imageGeometry).toBeNull();
  });
});

describe("toPrintUiModel - owned-asset provenance", () => {
  const OFFICIAL = "https://pub-test.r2.dev/display-images/sha256/aa/aa.png";

  it("carries owned_asset_selected through when true", () => {
    const model = toPrintUiModel(
      catalogueItem({
        display_image: {
          url: OFFICIAL,
          source: "bandai",
          exact_print_verified: true,
          owned_asset_selected: true,
          geometry: null,
        },
      }),
    );
    expect(model.imageSource).toBe("bandai");
    expect(model.imageOwnedAssetSelected).toBe(true);
  });

  it("carries it through when false - the canonical fallback", () => {
    const model = toPrintUiModel(
      catalogueItem({
        display_image: {
          url: "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001.png",
          source: "bandai",
          exact_print_verified: true,
          owned_asset_selected: false,
          geometry: null,
        },
      }),
    );
    expect(model.imageSource).toBe("bandai");
    expect(model.imageOwnedAssetSelected).toBe(false);
  });

  it("defaults to false when an older response omits the field", () => {
    const model = toPrintUiModel(
      catalogueItem({
        display_image: {
          url: OFFICIAL,
          source: "bandai",
          exact_print_verified: true,
          geometry: null,
        },
      }),
    );
    expect(model.imageOwnedAssetSelected).toBe(false);
  });

  it("defaults to false when there is no display image at all", () => {
    expect(toPrintUiModel(catalogueItem({ display_image: null })).imageOwnedAssetSelected).toBe(false);
  });

  it("is never inferred from the URL host", () => {
    // An r2.dev URL with the flag absent must still read as not-owned: the
    // backend states provenance, the frontend never guesses it.
    const model = toPrintUiModel(
      catalogueItem({
        display_image: {
          url: OFFICIAL,
          source: "yuyutei",
          exact_print_verified: true,
          geometry: null,
        },
      }),
    );
    expect(model.imageUrl).toContain("r2.dev");
    expect(model.imageOwnedAssetSelected).toBe(false);
  });
});

describe("printing presentation", () => {
  it("derives the printing type from the asset variant only", () => {
    expect(toPrintUiModel(catalogueItem({ official_asset_variant: "base" })).printingType).toBeNull();
    expect(toPrintUiModel(catalogueItem({ official_asset_variant: "p2" })).printingType?.label).toBe(
      "Alt Art",
    );
    expect(toPrintUiModel(catalogueItem({ official_asset_variant: "r1" })).printingType?.label).toBe(
      "Reprint",
    );
  });

  it("carries the art ordinal but leaves showing it to the caller", () => {
    expect(toPrintUiModel(catalogueItem({ official_asset_variant: "p2" })).artOrdinal).toBe("Art 3");
    expect(toPrintUiModel(catalogueItem({ official_asset_variant: "base" })).artOrdinal).toBeNull();
  });

  it("keeps the original set separate from the product it was found in", () => {
    const model = toPrintUiModel(
      catalogueItem({ release_product_code: "PRB-02", original_set_code: "OP-09" }),
    );
    expect(model.releaseCode).toBe("PRB-02");
    expect(model.originalSetCode).toBe("OP-09");
  });

  it("tolerates an API response without the new fields", () => {
    const item = catalogueItem();
    delete (item as unknown as Record<string, unknown>).original_set_code;
    delete (item as unknown as Record<string, unknown>).official_asset_variant;
    const model = toPrintUiModel(item);
    expect(model.originalSetCode).toBeNull();
    expect(model.printingType).toBeNull();
    expect(model.artOrdinal).toBeNull();
  });
});

describe("rarity, special print and printing as three separate dimensions", () => {
  it("reads an ordinary print's rarity from its own published token", () => {
    const model = toPrintUiModel(catalogueItem({ rarity: "SR", canonical_rarity: "SR" }));

    expect(model.rarityTerm?.label).toBe("Super Rare");
    expect(model.rarityIsCardLevel).toBe(false);
    expect(model.specialPrint).toBeNull();
    expect(model.unknownRarityToken).toBeNull();
  });

  it("never presents SPカード as the card's rarity", () => {
    // The defect this whole split exists to fix: the SP token is a printing
    // category, so it must not land in the rarity slot under any circumstance.
    const model = toPrintUiModel(
      catalogueItem({ rarity: "SPカード", canonical_rarity: null }),
    );

    expect(model.specialPrint?.label).toBe("SP Card");
    expect(model.rarityTerm).toBeNull();
    expect(model.unknownRarityToken).toBeNull();
  });

  it("shows the underlying rarity alongside SP Card when the card has one", () => {
    // OP06-007 Shanks: published as SPカード in PRB-02, and Super Rare under
    // its own set OP-06. Both are true, and neither is derived from the other.
    const model = toPrintUiModel(
      catalogueItem({
        card_code: "OP06-007",
        rarity: "SPカード",
        canonical_rarity: "SR",
        official_asset_variant: "p2",
      }),
    );

    expect(model.rarityTerm?.label).toBe("Super Rare");
    expect(model.rarityIsCardLevel).toBe(true);
    expect(model.specialPrint?.label).toBe("SP Card");
    expect(model.printingType?.label).toBe("Alt Art");
  });

  it("treats SP P exactly as SPカード - one category, two published tokens", () => {
    const jp = toPrintUiModel(catalogueItem({ rarity: "SPカード" }));
    const alt = toPrintUiModel(catalogueItem({ rarity: "SP P" }));

    expect(alt.specialPrint?.key).toBe(jp.specialPrint?.key);
    expect(alt.specialPrint?.label).toBe("SP Card");
  });

  it("omits the rarity entirely rather than inventing one for a TR print", () => {
    // Both live TR prints have no card-level rarity, and nothing about the
    // product, the asset variant or a sibling may be used to fill it in.
    const model = toPrintUiModel(
      catalogueItem({
        card_code: "OP16-042",
        rarity: "TR",
        canonical_rarity: null,
        official_asset_variant: "p1",
      }),
    );

    expect(model.rarityTerm).toBeNull();
    expect(model.rarityIsCardLevel).toBe(false);
    expect(model.specialPrint?.label).toBe("Treasure Rare");
    expect(model.specialPrint?.shortLabel).toBe("TR");
    expect(model.printingType?.label).toBe("Alt Art");
  });

  it("refuses a card-level token that is itself a special print", () => {
    // One live promo carries SPカード in BOTH columns. That is not an
    // underlying rarity, so the rarity stays absent rather than repeating the
    // special print under a second heading.
    const model = toPrintUiModel(
      catalogueItem({ rarity: "SPカード", canonical_rarity: "SPカード" }),
    );

    expect(model.rarityTerm).toBeNull();
    expect(model.specialPrint?.label).toBe("SP Card");
  });

  it("ignores the card-level rarity when the print publishes its own", () => {
    const model = toPrintUiModel(catalogueItem({ rarity: "SR", canonical_rarity: "C" }));

    expect(model.rarityTerm?.label).toBe("Super Rare");
    expect(model.rarityIsCardLevel).toBe(false);
  });

  it("passes an unknown token through instead of guessing or dropping it", () => {
    const model = toPrintUiModel(catalogueItem({ rarity: "XR", canonical_rarity: null }));

    expect(model.unknownRarityToken).toBe("XR");
    expect(model.rarityTerm).toBeNull();
    expect(model.specialPrint).toBeNull();
    // The raw token survives on the model too, for provenance.
    expect(model.rarity).toBe("XR");
  });

  it("tolerates an API response with no canonical_rarity field at all", () => {
    const item = catalogueItem({ rarity: "SPカード" });
    delete item.canonical_rarity;

    const model = toPrintUiModel(item);

    expect(model.specialPrint?.label).toBe("SP Card");
    expect(model.rarityTerm).toBeNull();
  });
});

describe("printsNeedingArtOrdinal", () => {
  function model(id: number, overrides: Partial<PrintCatalogueItem> = {}) {
    return toPrintUiModel(catalogueItem({ card_print_id: id, ...overrides }));
  }

  it("marks nothing when every tile already reads differently", () => {
    const prints = [
      model(1, { official_asset_variant: "base" }),
      model(2, { official_asset_variant: "p1" }),
      model(3, { official_asset_variant: "r1" }),
    ];
    expect(printsNeedingArtOrdinal(prints).size).toBe(0);
  });

  it("marks prints whose whole visible label collides", () => {
    // Two alt arts of one card in one product: same name, code, product,
    // printing type and rarity - only the artwork differs.
    const prints = [
      model(10, { official_asset_variant: "p1" }),
      model(11, { official_asset_variant: "p2" }),
    ];
    const needing = printsNeedingArtOrdinal(prints);
    expect(needing.has(10)).toBe(true);
    expect(needing.has(11)).toBe(true);
  });

  it("never marks a print that has no ordinal to show", () => {
    // Two reprints would collide, but neither has an art ordinal, so marking
    // them would promise a distinction the data cannot make.
    const prints = [
      model(20, { official_asset_variant: "r1" }),
      model(21, { official_asset_variant: "r2" }),
    ];
    expect(printsNeedingArtOrdinal(prints).size).toBe(0);
  });

  it("collides two SP prints published under different raw tokens", () => {
    // They render identically - "SP Card" both - so the raw token difference
    // is invisible to a reader and cannot be what tells them apart.
    const needing = printsNeedingArtOrdinal([
      toPrintUiModel(
        catalogueItem({ card_print_id: 1, rarity: "SPカード", official_asset_variant: "p1" }),
      ),
      toPrintUiModel(
        catalogueItem({ card_print_id: 2, rarity: "SP P", official_asset_variant: "p2" }),
      ),
    ]);

    expect(needing).toEqual(new Set([1, 2]));
  });

  it("does not collide prints that differ by product", () => {
    const prints = [
      model(30, { official_asset_variant: "p1", release_product_code: "OP-05" }),
      model(31, { official_asset_variant: "p1", release_product_code: "PRB-01" }),
    ];
    expect(printsNeedingArtOrdinal(prints).size).toBe(0);
  });
});
