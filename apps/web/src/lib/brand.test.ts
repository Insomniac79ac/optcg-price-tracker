import { describe, expect, it } from "vitest";

import { brand } from "./brand";

describe("brand", () => {
  it("centralizes the current working product name and endorsement", () => {
    expect(brand.productName).toBe("CardPirate Atlas");
    expect(brand.shortName).toBe("Atlas");
    expect(brand.parentBrand).toBe("CardPirateTCG");
    expect(brand.endorsementLine).toBe("by CardPirateTCG");
  });

  it("centralizes the tagline and supporting line", () => {
    expect(brand.tagline).toBe("Map your collection. Find your next treasure.");
    expect(brand.supportingLine).toBe("Collect the story. Know the value.");
  });

  it("never claims official status in the legal disclaimer", () => {
    expect(brand.legalDisclaimer).toMatch(/independent collector tool/i);
    expect(brand.legalDisclaimer).toMatch(/not affiliated with/i);
  });

  it("retains functional (non-novelty) public navigation labels", () => {
    expect(brand.nav).toMatchObject({
      discover: "Discover",
      cards: "Cards",
      marketIndex: "Market Index",
      myCollection: "My Collection",
      wishlist: "Wishlist",
      grading: "Grading",
      activity: "Activity",
      admin: "Admin",
    });
  });

  it("metadata title template applies the product name as a suffix", () => {
    expect(brand.metadataTitleTemplate).toBe("%s — CardPirate Atlas");
  });
});
