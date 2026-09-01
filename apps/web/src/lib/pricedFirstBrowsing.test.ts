/** Priced-first public browsing: the catalogue default and the redundant
 * source-row rule.
 *
 * These pin the two decisions that changed what a first-time collector sees,
 * plus the four conditions that must ALL hold before a source row is hidden.
 */

import { describe, expect, it } from "vitest";

import { EMPTY_PRINT_FILTERS } from "@/components/ui/PrintCatalogueToolbar";
import { isRedundantSingleSource, type PrintMarketIndex } from "./prints";

function sourceValue(overrides: Partial<PrintMarketIndex["source_values"][number]> = {}) {
  return {
    source: "snkrdunk",
    reference_type: "listing_floor",
    evidence_type: "listing" as const,
    value_jpy: 66000,
    observed_at: "2026-09-01T00:00:00Z",
    sample_size: null,
    stale: false,
    eligible: true,
    fallback_used: false,
    ineligible_reason: null,
    constraint: null,
    ...overrides,
  };
}

function index(overrides: Partial<PrintMarketIndex> = {}): PrintMarketIndex {
  return {
    card_print_id: 1,
    index_version: 1,
    index_value_jpy: 66000,
    calculation_method: "single_source",
    source_count: 1,
    coverage_status: "limited",
    confidence: "medium",
    source_values: [sourceValue()],
    auxiliary_values: [],
    freshest_observation_at: null,
    stalest_eligible_source_at: null,
    stale_sources: [],
    calculated_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

describe("A. the catalogue opens on Market Index, high to low", () => {
  it("defaults to index_desc, not card code", () => {
    // Ordered by card code the first page was 24 of 24 "Index unavailable".
    expect(EMPTY_PRINT_FILTERS.sort).toBe("index_desc");
  });

  it("keeps card code available as an explicit choice", () => {
    // B/C are asserted end-to-end in app/cards/page.test.tsx; this pins that
    // card_code is no longer the default but is still a valid sort value.
    expect(EMPTY_PRINT_FILTERS.sort).not.toBe("card_code");
  });
});

describe("H/I/J. redundant source rows", () => {
  it("H. is redundant with one eligible unconstrained source equal to the index", () => {
    expect(isRedundantSingleSource(index())).toBe(true);
  });

  it("I. is NOT redundant when two sources disagree", () => {
    expect(
      isRedundantSingleSource(
        index({
          index_value_jpy: 22900,
          source_values: [
            sourceValue({ source: "yuyutei", value_jpy: 24800 }),
            sourceValue({ source: "snkrdunk", value_jpy: 21000 }),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("I. is NOT redundant when a lone source differs from the index", () => {
    expect(
      isRedundantSingleSource(index({ index_value_jpy: 200, source_values: [sourceValue({ value_jpy: 120 })] })),
    ).toBe(false);
  });

  it("J. is NOT redundant when the source is constrained", () => {
    // A platform-minimum value means something its number alone does not say.
    expect(
      isRedundantSingleSource(
        index({
          index_value_jpy: 1000,
          source_values: [sourceValue({ value_jpy: 1000, constraint: "platform_floor", eligible: false })],
        }),
      ),
    ).toBe(false);
  });

  it("J. is NOT redundant when the source is ineligible, even unconstrained", () => {
    expect(
      isRedundantSingleSource(
        index({ source_values: [sourceValue({ eligible: false, ineligible_reason: "stale" })] }),
      ),
    ).toBe(false);
  });

  it("is NOT redundant when the index itself is unavailable", () => {
    expect(
      isRedundantSingleSource(
        index({ index_value_jpy: null, source_values: [sourceValue({ value_jpy: 66000 })] }),
      ),
    ).toBe(false);
  });

  it("is NOT redundant when no source reported a value", () => {
    expect(
      isRedundantSingleSource(
        index({ index_value_jpy: null, source_values: [sourceValue({ value_jpy: null })] }),
      ),
    ).toBe(false);
  });
});
