/** `resolveCanonicalPrintIdentity` fails closed, by design.
 *
 * The rule it enforces is narrow and deliberately unclever: one canonical card
 * and one name across EVERY record, or nothing. These tests pin the "or
 * nothing" half, because that is the half a future convenience change would
 * erode - a `.trim()`, a case fold, a "just take the first one".
 */

import { describe, expect, it } from "vitest";

import { resolveCanonicalPrintIdentity, type PrintCatalogueItem } from "./prints";

function item(overrides: Partial<PrintCatalogueItem> = {}): PrintCatalogueItem {
  return {
    card_print_id: 1,
    canonical_card_id: 7,
    card_code: "OP01-001",
    name_en: "Roronoa Zoro",
    name_jp: "ロロノア・ゾロ",
    rarity: "L",
    canonical_rarity: "L",
    card_type: "Leader",
    treatment: "normal",
    language: "jp",
    release_product_code: "OP-01",
    original_set_code: "OP-01",
    official_asset_variant: "base",
    image_url: null,
    display_image: null,
    verification_status: "verified",
    market_index: {
      card_print_id: 1,
      index_version: 1,
      index_value_jpy: null,
      calculation_method: "none",
      source_count: 0,
      coverage_status: "none",
      confidence: "low",
      source_values: [],
      auxiliary_values: [],
      freshest_observation_at: null,
      stalest_eligible_source_at: null,
      stale_sources: [],
      calculated_at: "2026-09-01T00:00:00Z",
    },
    source_coverage: [],
    latest_observation_at: null,
    ...overrides,
  };
}

describe("resolveCanonicalPrintIdentity", () => {
  it("returns the agreed canonical name and id", () => {
    expect(
      resolveCanonicalPrintIdentity([item(), item({ card_print_id: 2, treatment: "parallel" })]),
    ).toEqual({ canonicalCardId: 7, name: "Roronoa Zoro" });
  });

  it("returns null for an empty result set rather than an empty name", () => {
    expect(resolveCanonicalPrintIdentity([])).toBeNull();
  });

  it("returns null when the records span two canonical cards", () => {
    expect(
      resolveCanonicalPrintIdentity([item(), item({ card_print_id: 2, canonical_card_id: 8 })]),
    ).toBeNull();
  });

  it("returns null on any name disagreement, and never picks the first", () => {
    const disagreeing = [item(), item({ card_print_id: 2, name_en: "Roronoa Zolo" })];
    expect(resolveCanonicalPrintIdentity(disagreeing)).toBeNull();
    // The reverse order must give the same answer - no positional authority.
    expect(resolveCanonicalPrintIdentity([...disagreeing].reverse())).toBeNull();
  });

  it("treats a punctuation-only difference as a disagreement, not a match", () => {
    // "Portgas D. Ace" vs "Portgas.D.Ace" really occurs between the legacy and
    // canonical corpora. No normalisation: unequal is unequal.
    expect(
      resolveCanonicalPrintIdentity([
        item({ name_en: "Portgas D. Ace" }),
        item({ card_print_id: 2, name_en: "Portgas.D.Ace" }),
      ]),
    ).toBeNull();
  });

  it("falls back to the Japanese name only when English is absent everywhere", () => {
    expect(
      resolveCanonicalPrintIdentity([
        item({ name_en: null }),
        item({ card_print_id: 2, name_en: null }),
      ]),
    ).toEqual({ canonicalCardId: 7, name: "ロロノア・ゾロ" });
  });

  it("returns null when a record carries no usable name at all", () => {
    expect(resolveCanonicalPrintIdentity([item({ name_en: null, name_jp: null })])).toBeNull();
  });
});
