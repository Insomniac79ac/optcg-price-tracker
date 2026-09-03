import { describe, expect, it } from "vitest";

import {
  contributionQualifier,
  displayedSourceValues,
  isReferenceOnly,
  rangeIncludesReferenceOnly,
  REFERENCE_ONLY_EXPLANATION,
  REFERENCE_ONLY_LABEL,
  REFERENCE_ONLY_RANGE_CAPTION,
} from "./sourceContribution";

function value(overrides: Partial<{
  value_jpy: number | null;
  eligible: boolean;
  contributes_to_index: boolean | null;
}> = {}) {
  return { value_jpy: 120, eligible: true, contributes_to_index: true, ...overrides };
}

describe("isReferenceOnly", () => {
  it("is true only for an explicit false", () => {
    expect(isReferenceOnly({ contributes_to_index: false })).toBe(true);
    expect(isReferenceOnly({ contributes_to_index: true })).toBe(false);
  });

  // The wire type is bool | None, and None means "this payload predates the
  // field", never "it did not contribute". Reading null as an exclusion would
  // stamp "Reference only" on every price served by an older API.
  it("is false for a payload that predates the field", () => {
    expect(isReferenceOnly({ contributes_to_index: null })).toBe(false);
    expect(isReferenceOnly({})).toBe(false);
  });

  // Contribution is never re-derived. A fallback source that DID contribute -
  // because it was the only admissible value on the print - is not
  // reference-only, however much its other fields look like the excluded case.
  it("follows the field, not eligible or fallback_used", () => {
    const countedFallback = { eligible: true, fallback_used: true, contributes_to_index: true };
    const standAsideNonFallback = {
      eligible: true,
      fallback_used: false,
      contributes_to_index: false,
    };
    expect(isReferenceOnly(countedFallback)).toBe(false);
    expect(isReferenceOnly(standAsideNonFallback)).toBe(true);
  });
});

describe("displayedSourceValues", () => {
  it("keeps only the sources that actually reported a price", () => {
    const rows = [value(), value({ value_jpy: null })];
    expect(displayedSourceValues(rows)).toHaveLength(1);
  });
});

describe("contributionQualifier", () => {
  // Print 5998: SNKRDUNK's ¥2,500 is admissible but stood aside, so the
  // backend counted one input behind a page showing two prices.
  it("states the backend's own input count against the prices on screen", () => {
    expect(
      contributionQualifier({
        source_count: 1,
        source_values: [value(), value({ value_jpy: 2500, contributes_to_index: false })],
      }),
    ).toBe("1 of 2 source prices used");
  });

  it("says nothing when the index counted every visible price", () => {
    expect(
      contributionQualifier({
        source_count: 2,
        source_values: [value(), value({ value_jpy: 130 })],
      }),
    ).toBeNull();
  });

  // THE POINT OF THIS TEST. Contribution membership here says all three
  // prices contributed; source_count says one did. The published count wins,
  // because re-deriving it in the browser is how the sentence and the number
  // it sits under would drift apart.
  it("follows source_count, not locally inferred contribution membership", () => {
    expect(
      contributionQualifier({
        source_count: 1,
        source_values: [
          value({ contributes_to_index: true }),
          value({ value_jpy: 2500, contributes_to_index: true }),
          value({ value_jpy: 900, contributes_to_index: true }),
        ],
      }),
    ).toBe("1 of 3 source prices used");
  });

  // The mirror of the case above: every visible price is flagged as excluded,
  // yet source_count says both were counted, so there is nothing to qualify.
  it("stays silent when source_count matches, whatever the flags say", () => {
    expect(
      contributionQualifier({
        source_count: 2,
        source_values: [
          value({ contributes_to_index: false }),
          value({ value_jpy: 2500, contributes_to_index: false }),
        ],
      }),
    ).toBeNull();
  });

  // Print 12: the excluded value is an ineligible platform floor rather than
  // a fallback standing aside. Two prices are on screen and the index was
  // computed from one, so the sentence is the same and still true.
  it("counts an ineligible visible price in the denominator", () => {
    expect(
      contributionQualifier({
        source_count: 1,
        source_values: [
          value({ value_jpy: 80 }),
          value({
            value_jpy: 1000,
            eligible: false,
            contributes_to_index: false,
          }),
        ],
      }),
    ).toBe("1 of 2 source prices used");
  });

  // A SNKRDUNK-floor-only print: nothing was admissible, so there is no index
  // at all - and "0 of 1" is exactly what explains that.
  it("states a zero count beside an unavailable index", () => {
    expect(
      contributionQualifier({
        source_count: 0,
        source_values: [
          value({ value_jpy: 1000, eligible: false, contributes_to_index: false }),
        ],
      }),
    ).toBe("0 of 1 source prices used");
  });

  // Print 5997's real shape: SNKRDUNK is present in source_values with
  // value_jpy null, so it has no panel and must not swell the denominator.
  it("does not count a source that reported no price", () => {
    expect(
      contributionQualifier({
        source_count: 1,
        source_values: [
          value({ value_jpy: 80 }),
          value({ value_jpy: null, contributes_to_index: false }),
        ],
      }),
    ).toBeNull();
  });

  // Nothing here reads contributes_to_index, so an API that predates the
  // field qualifies exactly as a current one does.
  it("needs no contributes_to_index at all", () => {
    expect(
      contributionQualifier({
        source_count: 1,
        source_values: [
          { value_jpy: 120, eligible: true },
          { value_jpy: 2500, eligible: true },
        ],
      }),
    ).toBe("1 of 2 source prices used");
  });

  // Defensive: a payload claiming more inputs than it shows prices for is
  // incoherent, and inventing "3 of 2 source prices used" would broadcast it.
  it("says nothing when source_count exceeds the prices on screen", () => {
    expect(
      contributionQualifier({ source_count: 3, source_values: [value()] }),
    ).toBeNull();
  });
});

describe("rangeIncludesReferenceOnly", () => {
  it("is true for an admissible price that did not feed the index", () => {
    expect(
      rangeIncludesReferenceOnly([
        value(),
        value({ value_jpy: 2500, contributes_to_index: false }),
      ]),
    ).toBe(true);
  });

  // An ineligible price is not admissible, so it is not inside
  // source_price_range at all and a caption claiming otherwise would be false.
  it("is false for an ineligible non-contributor", () => {
    expect(
      rangeIncludesReferenceOnly([
        value(),
        value({ value_jpy: 1000, eligible: false, contributes_to_index: false }),
      ]),
    ).toBe(false);
  });

  it("is false when every visible price contributed", () => {
    expect(rangeIncludesReferenceOnly([value(), value({ value_jpy: 130 })])).toBe(false);
  });
});

describe("copy", () => {
  // Pinned verbatim: this is the wording the tranche was specified in, and it
  // must not drift into "market range" or a spread/warning vocabulary.
  it("is the agreed collector-facing wording", () => {
    expect(REFERENCE_ONLY_LABEL).toBe("Reference only");
    expect(REFERENCE_ONLY_EXPLANATION).toBe(
      "Shown for context; not used in Market Index.",
    );
    expect(REFERENCE_ONLY_RANGE_CAPTION).toBe(
      "Includes reference-only source prices.",
    );
  });
});
