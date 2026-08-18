import { describe, expect, it } from "vitest";

import {
  HERO_FAN_SIZE,
  isHeroFanEligible,
  prefersHeroFanImage,
  selectHeroFanPrints,
  utcDayKey,
} from "./heroFan";
import type { PrintMarketIndex, PrintUiModel } from "./prints";

const EMPTY_INDEX: PrintMarketIndex = {
  card_print_id: 0,
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
  calculated_at: "2026-08-17T00:00:00Z",
};

/** A print built from its id, so nothing in these tests depends on a
 * particular real card. */
function print(id: number, overrides: Partial<PrintUiModel> = {}): PrintUiModel {
  const code = `SET-${String(id).padStart(3, "0")}`;
  return {
    cardPrintId: id,
    cardCode: code,
    nameEn: `Card ${id}`,
    nameJp: null,
    displayName: `Card ${id}`,
    rarity: "R",
    cardType: "Character",
    treatment: "normal",
    isDistinctTreatment: false,
    language: "jp",
    releaseCode: "SET",
    imageUrl: `https://example.test/art/${id}.png`,
    sourceImageUrl: `https://example.test/art/${id}.png`,
    imageSource: "snkrdunk",
    imageExactPrintVerified: true,
    imageOwnedAssetSelected: true,
    imageGeometry: null,
    marketIndexJpy: null,
    yuyuteiJpy: null,
    snkrdunkJpy: null,
    sourceCount: 0,
    coverageStatus: "none",
    confidence: "low",
    contributingSources: [],
    latestObservationAt: null,
    marketIndex: { ...EMPTY_INDEX, card_print_id: id },
    ...overrides,
  };
}

/** A print whose only image is the canonical Bandai artwork - eligible, but
 * only after the verified ones. */
function fallbackPrint(id: number, overrides: Partial<PrintUiModel> = {}): PrintUiModel {
  return print(id, {
    imageSource: null,
    imageExactPrintVerified: null,
    imageOwnedAssetSelected: false,
    ...overrides,
  });
}

/** The canonical ONE PIECE Card List fallback: same `imageSource` as an owned
 * official asset, and no owned asset behind it. */
function canonicalBandaiPrint(id: number, overrides: Partial<PrintUiModel> = {}): PrintUiModel {
  return print(id, {
    imageSource: "bandai",
    imageExactPrintVerified: true,
    imageOwnedAssetSelected: false,
    ...overrides,
  });
}

/** A verified asset we mirrored ourselves, from any source. */
function ownedPrint(id: number, source: string): PrintUiModel {
  return print(id, {
    imageSource: source,
    imageExactPrintVerified: true,
    imageOwnedAssetSelected: true,
  });
}

const POOL = Array.from({ length: 12 }, (_, i) => print(i + 1));
const ids = (prints: PrintUiModel[]) => prints.map((p) => p.cardPrintId);

const TODAY = "2026-08-17";

describe("utcDayKey", () => {
  it("is the UTC calendar day, not the local one", () => {
    // 23:30 on the 17th in UTC+9 is still the 17th in UTC; the point is that
    // the key is computed from the UTC clock so every visitor shares it.
    expect(utcDayKey(new Date("2026-08-17T14:30:00Z"))).toBe("2026-08-17");
    expect(utcDayKey(new Date("2026-08-17T23:59:59Z"))).toBe("2026-08-17");
    expect(utcDayKey(new Date("2026-08-18T00:00:00Z"))).toBe("2026-08-18");
  });
});

describe("selectHeroFanPrints", () => {
  it("selects exactly three prints when at least three are eligible", () => {
    expect(selectHeroFanPrints(POOL, TODAY)).toHaveLength(HERO_FAN_SIZE);
    expect(selectHeroFanPrints(POOL.slice(0, 3), TODAY)).toHaveLength(HERO_FAN_SIZE);
  });

  it("never repeats a card_print_id", () => {
    for (let day = 1; day <= 31; day += 1) {
      const key = `2026-08-${String(day).padStart(2, "0")}`;
      const picked = ids(selectHeroFanPrints(POOL, key));
      expect(new Set(picked).size).toBe(picked.length);
    }
  });

  it("returns the same three for the same day and the same catalogue", () => {
    expect(ids(selectHeroFanPrints(POOL, TODAY))).toEqual(ids(selectHeroFanPrints(POOL, TODAY)));
  });

  it("rotates: a different day can produce a different three", () => {
    const seen = new Set<string>();
    for (let day = 1; day <= 31; day += 1) {
      seen.add(ids(selectHeroFanPrints(POOL, `2026-08-${String(day).padStart(2, "0")}`)).join(","));
    }
    expect(seen.size).toBeGreaterThan(1);
  });

  it("ignores the order it is handed, so re-sorting the catalogue changes nothing", () => {
    // Sort order is the visitor's choice; the fan is not a view of it.
    const reversed = [...POOL].reverse();
    const byCode = [...POOL].sort((a, b) => b.cardCode.localeCompare(a.cardCode));
    expect(ids(selectHeroFanPrints(reversed, TODAY))).toEqual(ids(selectHeroFanPrints(POOL, TODAY)));
    expect(ids(selectHeroFanPrints(byCode, TODAY))).toEqual(ids(selectHeroFanPrints(POOL, TODAY)));
  });

  it("skips prints with no usable image rather than drawing a placeholder", () => {
    const pool = [
      print(1, { imageUrl: null }),
      print(2, { imageUrl: "   " }),
      ...POOL.slice(2),
    ];
    const picked = ids(selectHeroFanPrints(pool, TODAY));
    expect(picked).not.toContain(1);
    expect(picked).not.toContain(2);
    expect(picked).toHaveLength(HERO_FAN_SIZE);
  });

  it("skips images the API has verified are NOT this exact print", () => {
    const wrongPrint = print(1, { imageExactPrintVerified: false });
    expect(isHeroFanEligible(wrongPrint)).toBe(false);
    expect(ids(selectHeroFanPrints([wrongPrint], TODAY))).toEqual([]);
  });

  it("keeps canonical artwork eligible, since it carries no such evidence either way", () => {
    const canonical = fallbackPrint(1);
    expect(isHeroFanEligible(canonical)).toBe(true);
    expect(prefersHeroFanImage(canonical)).toBe(false);
    expect(ids(selectHeroFanPrints([canonical], TODAY))).toEqual([1]);
  });

  it("prefers verified self-hosted images over the canonical fallback", () => {
    const pool = [
      ...Array.from({ length: 8 }, (_, i) => fallbackPrint(i + 1)),
      print(20),
      print(21),
      print(22),
    ];
    expect(ids(selectHeroFanPrints(pool, TODAY)).sort((a, b) => a - b)).toEqual([20, 21, 22]);
  });

  it("tops up from the fallback tier when too few verified images exist", () => {
    const pool = [print(20), ...Array.from({ length: 6 }, (_, i) => fallbackPrint(i + 1))];
    const picked = selectHeroFanPrints(pool, TODAY);
    expect(picked).toHaveLength(HERO_FAN_SIZE);
    // The one verified image leads the composition; the rest fill in behind.
    expect(picked[0].cardPrintId).toBe(20);
    expect(picked.filter(prefersHeroFanImage)).toHaveLength(1);
  });

  it("avoids two prints of the same card, and the same artwork twice", () => {
    const siblings = [
      print(1, { cardCode: "SET-001", sourceImageUrl: "https://example.test/art/a.png" }),
      print(2, { cardCode: "SET-001", sourceImageUrl: "https://example.test/art/a.png" }),
      print(3, { cardCode: "SET-002", sourceImageUrl: "https://example.test/art/a.png" }),
      print(4, { cardCode: "SET-003", sourceImageUrl: "https://example.test/art/b.png" }),
      print(5, { cardCode: "SET-004", sourceImageUrl: "https://example.test/art/c.png" }),
      print(6, { cardCode: "SET-005", sourceImageUrl: "https://example.test/art/d.png" }),
    ];
    for (let day = 1; day <= 31; day += 1) {
      const picked = selectHeroFanPrints(siblings, `2026-08-${String(day).padStart(2, "0")}`);
      expect(picked).toHaveLength(HERO_FAN_SIZE);
      expect(new Set(picked.map((p) => p.cardCode)).size).toBe(HERO_FAN_SIZE);
      expect(new Set(picked.map((p) => p.sourceImageUrl)).size).toBe(HERO_FAN_SIZE);
    }
  });

  it("relaxes variety rather than returning short when the catalogue is that small", () => {
    // Three prints of one card with one shared artwork: variety is impossible,
    // and three real distinct prints still beat an empty panel.
    const oneCard = [
      print(1, { cardCode: "SET-001", sourceImageUrl: "https://example.test/art/a.png" }),
      print(2, { cardCode: "SET-001", sourceImageUrl: "https://example.test/art/a.png" }),
      print(3, { cardCode: "SET-001", sourceImageUrl: "https://example.test/art/a.png" }),
    ];
    const picked = selectHeroFanPrints(oneCard, TODAY);
    expect(picked).toHaveLength(HERO_FAN_SIZE);
    expect(new Set(ids(picked)).size).toBe(HERO_FAN_SIZE);
  });

  it("degrades to what is actually there when fewer than three are eligible", () => {
    const twoGoodOneBad = [print(1), print(2), print(3, { imageUrl: null })];
    const picked = selectHeroFanPrints(twoGoodOneBad, TODAY);
    // Exactly the eligible ones - never padded back up to three with the
    // print that has no image.
    expect(ids(picked).sort((a, b) => a - b)).toEqual([1, 2]);
    expect(ids(selectHeroFanPrints([print(1)], TODAY))).toEqual([1]);
  });

  it("returns nothing when nothing is eligible", () => {
    expect(selectHeroFanPrints([], TODAY)).toEqual([]);
    expect(selectHeroFanPrints([print(1, { imageUrl: null })], TODAY)).toEqual([]);
    expect(selectHeroFanPrints([print(1, { imageExactPrintVerified: false })], TODAY)).toEqual([]);
  });
});

describe("prefersHeroFanImage - provenance, not source name", () => {
  it("prefers an owned official Card List image", () => {
    expect(prefersHeroFanImage(ownedPrint(1, "bandai"))).toBe(true);
  });

  it("does not prefer the canonical Bandai fallback, despite the same source", () => {
    const canonical = canonicalBandaiPrint(1);
    expect(canonical.imageSource).toBe("bandai");
    expect(prefersHeroFanImage(canonical)).toBe(false);
    // ...and the owned one differs only in provenance, not in source name.
    expect(ownedPrint(2, "bandai").imageSource).toBe("bandai");
    expect(prefersHeroFanImage(ownedPrint(2, "bandai"))).toBe(true);
  });

  it.each(["yuyutei", "snkrdunk"])("keeps owned %s images preferred", (source) => {
    expect(prefersHeroFanImage(ownedPrint(1, source))).toBe(true);
  });

  it("does not prefer an owned image the API says is not this exact print", () => {
    const wrong = print(1, { imageOwnedAssetSelected: true, imageExactPrintVerified: false });
    expect(prefersHeroFanImage(wrong)).toBe(false);
  });

  it("does not rank sources against each other", () => {
    // All three owned: none outranks another here, because the backend has
    // already chosen the best source for each print.
    const owned = ["bandai", "yuyutei", "snkrdunk"].map((s, i) => ownedPrint(i + 1, s));
    expect(owned.every(prefersHeroFanImage)).toBe(true);
  });

  it("prefers owned images over canonical ones in the fan itself", () => {
    const pool = [
      ...Array.from({ length: 8 }, (_, i) => canonicalBandaiPrint(i + 1)),
      ownedPrint(20, "bandai"),
      ownedPrint(21, "yuyutei"),
      ownedPrint(22, "snkrdunk"),
    ];
    expect(ids(selectHeroFanPrints(pool, TODAY)).sort((a, b) => a - b)).toEqual([20, 21, 22]);
  });

  it("still fills the fan when every print is canonical", () => {
    const pool = Array.from({ length: 6 }, (_, i) => canonicalBandaiPrint(i + 1));
    const picked = selectHeroFanPrints(pool, TODAY);
    expect(picked).toHaveLength(HERO_FAN_SIZE);
    expect(picked.filter(prefersHeroFanImage)).toHaveLength(0);
  });

  it("is deterministic for a day regardless of provenance mix", () => {
    const pool = [
      ownedPrint(1, "bandai"),
      canonicalBandaiPrint(2),
      ownedPrint(3, "yuyutei"),
      canonicalBandaiPrint(4),
      ownedPrint(5, "snkrdunk"),
    ];
    expect(ids(selectHeroFanPrints(pool, TODAY))).toEqual(ids(selectHeroFanPrints(pool, TODAY)));
    expect(ids(selectHeroFanPrints([...pool].reverse(), TODAY))).toEqual(
      ids(selectHeroFanPrints(pool, TODAY)),
    );
  });
});
