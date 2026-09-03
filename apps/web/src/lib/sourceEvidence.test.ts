/** The evidence-type vocabulary: what a source value IS, said neutrally.
 *
 * Two things are being pinned here. First the wording itself, because the copy
 * is a product decision and a silent edit to "Current listing" would change
 * what Atlas promises a collector about an asking price. Second - and more
 * durably - that this module keys on `reference_type` ALONE, so a future
 * source's retail price is labelled correctly on the day it ships without
 * anyone touching this file.
 */

import { describe, expect, it } from "vitest";

import { describeSourceEvidence, sourceEvidenceLabel } from "./sourceEvidence";

describe("evidence-type labels", () => {
  it("calls a marketplace's cheapest open listing a current listing", () => {
    expect(sourceEvidenceLabel("listing_floor")).toBe("Current listing");
  });

  it("calls a median of completed sales a recent sales median", () => {
    expect(sourceEvidenceLabel("transaction_median")).toBe("Recent sales median");
  });

  it("calls a shop's displayed selling price a retail price", () => {
    expect(sourceEvidenceLabel("retail_sell")).toBe("Retail price");
  });

  it("calls a dealer's standing offer a dealer buy price", () => {
    expect(sourceEvidenceLabel("dealer_buy")).toBe("Dealer buy price");
  });
});

describe("evidence-type explanations", () => {
  it("tells a collector an asking price is not a completed sale", () => {
    // The product decision's own wording, verbatim: this is the sentence that
    // keeps a listing from being read as a sale now that eligible listings
    // count toward Market Index.
    expect(describeSourceEvidence("listing_floor")?.explanation).toBe(
      "Lowest current listing observed on this source. Asking prices are not completed sales and may differ from the price a card ultimately sells for.",
    );
  });

  it("says a sales median describes transactions that actually happened", () => {
    const explanation = describeSourceEvidence("transaction_median")!.explanation;
    expect(explanation).toMatch(/completed sales/);
    expect(explanation).toMatch(/actually/);
  });

  it("says a retail price is a price being asked", () => {
    expect(describeSourceEvidence("retail_sell")!.explanation).toMatch(
      /not completed sales/,
    );
  });

  it("says a dealer buy price never counts toward Market Index", () => {
    // The one evidence type whose exclusion is a property of the type itself,
    // not of anything wrong with the value.
    expect(describeSourceEvidence("dealer_buy")!.explanation).toMatch(
      /never count toward Market Index/,
    );
  });
});

describe("neutrality", () => {
  it("carries no tone, severity or warning vocabulary", () => {
    // These describe what a number is. Nothing here may read as an error, a
    // caveat or a downgrade - an eligible current listing contributes to
    // Market Index exactly like an eligible sold median.
    for (const referenceType of [
      "retail_sell",
      "transaction_median",
      "listing_floor",
      "dealer_buy",
    ]) {
      const copy = describeSourceEvidence(referenceType)!;
      expect(Object.keys(copy).sort()).toEqual(["explanation", "label"]);
      expect(`${copy.label} ${copy.explanation}`).not.toMatch(
        /warning|caution|error|unreliable|invalid|excluded|anomal/i,
      );
    }
  });

  it("never names a source or quotes a threshold", () => {
    // The source's identity is already on screen beside the price, and a
    // threshold restated here would be a second, silently-drifting copy of a
    // backend rule this app does not own.
    for (const referenceType of [
      "retail_sell",
      "transaction_median",
      "listing_floor",
      "dealer_buy",
    ]) {
      const copy = describeSourceEvidence(referenceType)!;
      const text = `${copy.label} ${copy.explanation}`;
      expect(text).not.toMatch(/yuyu|snkrdunk|cardrush|mercado|cardmarket/i);
      expect(text).not.toMatch(/[¥￥]|\d+\s*(days?|yen)/i);
    }
  });
});

describe("a reference type this build has never heard of", () => {
  it("passes the API's own identifier through rather than inventing a label", () => {
    // Same rule sourceDisplayName uses for an unknown source name: name the
    // thing with the identifier that exists, claim nothing about it.
    expect(sourceEvidenceLabel("auction_close")).toBe("auction_close");
  });

  it("offers no explanation, because this build has none to give", () => {
    expect(describeSourceEvidence("auction_close")).toBeNull();
    expect(describeSourceEvidence(null)).toBeNull();
    expect(describeSourceEvidence(undefined)).toBeNull();
    expect(describeSourceEvidence("")).toBeNull();
  });
});
