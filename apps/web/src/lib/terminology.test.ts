import { describe, expect, it } from "vitest";

import {
  artOrdinalLabel,
  classifyRarityToken,
  getTerm,
  KNOWN_RARITY_TOKENS,
  KNOWN_SPECIAL_PRINT_TOKENS,
  LEGEND_INTRO,
  LEGEND_SECTIONS,
  LEGEND_TERMS,
  printingTypeTerm,
  rarityTerm,
  SP_CARD_FILTER_VALUE,
  specialPrintTerm,
} from "./terminology";

describe("printing type", () => {
  it("gives a base printing no badge at all", () => {
    // Its absence is the signal that the alt art beside it is the different one.
    expect(printingTypeTerm("base")).toBeNull();
  });

  it("labels every p-family variant Alt Art, never Parallel", () => {
    for (const variant of ["p1", "p2", "p3", "p10"]) {
      const term = printingTypeTerm(variant);
      expect(term?.label).toBe("Alt Art");
      expect(term?.definition).toBe("Another official artwork of the same card.");
    }
    // Bandai publishes "(Parallel)" on only some p-variants, so it can never
    // be the definition of the family.
    expect(JSON.stringify(printingTypeTerm("p1"))).not.toContain("Parallel");
  });

  it("labels every r-family variant Reprint", () => {
    for (const variant of ["r1", "r2", "r3"]) {
      expect(printingTypeTerm(variant)?.label).toBe("Reprint");
    }
  });

  it("returns null rather than inventing a label for an unknown family", () => {
    // A future asset family is unrecognised evidence, not something to guess.
    expect(printingTypeTerm("x1")).toBeNull();
    expect(printingTypeTerm("p")).toBeNull();
    expect(printingTypeTerm("")).toBeNull();
    expect(printingTypeTerm(null)).toBeNull();
    expect(printingTypeTerm(undefined)).toBeNull();
  });
});

describe("art ordinal", () => {
  it("counts the base artwork, so p1 is the second art", () => {
    expect(artOrdinalLabel("p1")).toBe("Art 2");
    expect(artOrdinalLabel("p4")).toBe("Art 5");
  });

  it("has none for a base or reprint printing", () => {
    expect(artOrdinalLabel("base")).toBeNull();
    expect(artOrdinalLabel("r1")).toBeNull();
    expect(artOrdinalLabel(null)).toBeNull();
  });
});

describe("rarity", () => {
  it("uses Bandai's English-facing words", () => {
    expect(rarityTerm("C")?.label).toBe("Common");
    expect(rarityTerm("UC")?.label).toBe("Uncommon");
    expect(rarityTerm("R")?.label).toBe("Rare");
    expect(rarityTerm("SR")?.label).toBe("Super Rare");
    expect(rarityTerm("SEC")?.label).toBe("Secret Rare");
    expect(rarityTerm("L")?.label).toBe("Leader");
    expect(rarityTerm("P")?.label).toBe("Promo");
  });

  it("refuses to call a special-print token a rarity", () => {
    // The whole point of the split: SP Card and Treasure Rare are printing
    // categories, so there is no rarity to read out of these tokens at all.
    for (const token of ["SPカード", "SP P", "SP CARD", "TR"]) {
      expect(rarityTerm(token), `${token} must not resolve as a rarity`).toBeNull();
    }
  });

  it("falls back to nothing for an unknown rarity, inventing no meaning", () => {
    expect(rarityTerm("XYZ")).toBeNull();
    expect(rarityTerm(null)).toBeNull();
    expect(rarityTerm("  ")).toBeNull();
  });

  it("covers the ordinary rarity ladder and nothing else", () => {
    expect(new Set(KNOWN_RARITY_TOKENS)).toEqual(
      new Set(["C", "UC", "R", "SR", "SEC", "L", "P"]),
    );
  });
});

describe("special print", () => {
  it("renders every raw SP token as the single SP Card category", () => {
    // The English catalogue publishes both entries as SP CARD, so surfacing
    // them separately would invent a distinction Bandai does not make.
    for (const token of ["SPカード", "SP P", SP_CARD_FILTER_VALUE]) {
      expect(specialPrintTerm(token)?.label).toBe("SP Card");
    }
    expect(specialPrintTerm("SPカード")?.key).toBe(specialPrintTerm("SP P")?.key);
    expect(specialPrintTerm(SP_CARD_FILTER_VALUE)?.key).toBe(specialPrintTerm("SP P")?.key);
  });

  it("keeps the raw SP tokens available as provenance", () => {
    expect(specialPrintTerm("SPカード")?.sourceLabel).toBe("SPカード");
    expect(specialPrintTerm("SP P")?.sourceLabel).toBe("SP P");
  });

  it("says SP Card is not a scarcity tier and can sit beside one", () => {
    for (const token of ["SPカード", "SP P", SP_CARD_FILTER_VALUE]) {
      const definition = specialPrintTerm(token)?.definition ?? "";
      expect(definition).toContain("not a scarcity tier");
      expect(definition).toContain("alongside");
    }
  });

  it("names both raw tokens in the legend entry, and only there", () => {
    // The legend has no single print to point at, so it names both published
    // tokens itself. A per-print entry says which one THAT printing carries
    // through `sourceLabel` instead, so the detail row never says it twice.
    const legend = specialPrintTerm(SP_CARD_FILTER_VALUE)?.definition ?? "";
    expect(legend).toContain("SPカード");
    expect(legend).toContain("SP P");
    expect(specialPrintTerm("SPカード")?.definition).not.toContain("SP P");
  });

  it("keeps Treasure Rare separate from SP Card, with TR as the short badge", () => {
    expect(specialPrintTerm("TR")?.label).toBe("Treasure Rare");
    expect(specialPrintTerm("TR")?.shortLabel).toBe("TR");
    expect(specialPrintTerm("TR")?.key).not.toBe(specialPrintTerm("SPカード")?.key);
  });

  it("explains TR as language-specific, not one universal artwork", () => {
    expect(specialPrintTerm("TR")?.definition).toBe(
      "Treasure Rare. A language-specific special-art printing. Artwork may " +
        "differ between English, Japanese, Chinese and other editions.",
    );
  });

  it("never describes TR as a universal artwork or an ordinary rarity", () => {
    const definition = specialPrintTerm("TR")?.definition ?? "";
    expect(definition).not.toMatch(/universal/i);
    expect(definition.toLowerCase()).not.toContain("scarce");
    expect(rarityTerm("TR")).toBeNull();
  });

  it("names every token that resolves to a special print", () => {
    expect(new Set(KNOWN_SPECIAL_PRINT_TOKENS)).toEqual(
      new Set([SP_CARD_FILTER_VALUE, "SPカード", "SP P", "TR"]),
    );
  });
});

describe("classifying one published token", () => {
  it("puts an ordinary token in the rarity slot and nowhere else", () => {
    expect(classifyRarityToken("SR")).toEqual({
      rarity: rarityTerm("SR"),
      specialPrint: null,
      unknownToken: null,
    });
  });

  it("puts a special-print token in the special slot and nowhere else", () => {
    for (const token of ["SPカード", "SP P", "TR"]) {
      const facts = classifyRarityToken(token);
      expect(facts.rarity, `${token} leaked into the rarity slot`).toBeNull();
      expect(facts.specialPrint).not.toBeNull();
      expect(facts.unknownToken).toBeNull();
    }
  });

  it("passes an unknown token through verbatim rather than dropping it", () => {
    // Fail-safe: unfamiliar published evidence reaches the collector, unstyled
    // and undefined, instead of being guessed at or silently swallowed.
    expect(classifyRarityToken("XYZ")).toEqual({
      rarity: null,
      specialPrint: null,
      unknownToken: "XYZ",
    });
  });

  it("has nothing to say about an absent token", () => {
    for (const value of [null, undefined, "", "   "]) {
      expect(classifyRarityToken(value)).toEqual({
        rarity: null,
        specialPrint: null,
        unknownToken: null,
      });
    }
  });

  it("covers the complete live rarity vocabulary", () => {
    // Every token present in the 4,281-print staging corpus, plus the alias
    // the catalogue facets now publish in place of the two raw SP tokens.
    const live = ["C", "UC", "R", "SR", "SEC", "L", "P", "SPカード", "SP P", "TR"];
    for (const token of [...live, SP_CARD_FILTER_VALUE]) {
      const facts = classifyRarityToken(token);
      expect(facts.unknownToken, `${token} is unclassified`).toBeNull();
    }
    // Nine distinct collector-facing labels: the two SP tokens share one.
    const labels = live.map((token) => {
      const { rarity, specialPrint } = classifyRarityToken(token);
      return rarity?.label ?? specialPrint?.label;
    });
    expect(new Set(labels).size).toBe(9);
  });
});

describe("legend", () => {
  it("separates the three dimensions into their own sections", () => {
    const titles = LEGEND_SECTIONS.map((section) => section.title);
    expect(titles).toContain("Rarity");
    expect(titles).toContain("Special print");
    expect(titles).toContain("Printing");
    // Ordering matters: it is the same order the tile badges and the detail
    // rows read in.
    expect(titles.indexOf("Rarity")).toBeLessThan(titles.indexOf("Special print"));
    expect(titles.indexOf("Special print")).toBeLessThan(titles.indexOf("Printing"));
  });

  it("files SP Card and Treasure Rare under Special print, never under Rarity", () => {
    const rarity = LEGEND_SECTIONS.find((s) => s.title === "Rarity");
    const special = LEGEND_SECTIONS.find((s) => s.title === "Special print");
    expect(special?.terms.map((t) => t.label)).toEqual(["SP Card", "Treasure Rare"]);
    // The rarity section explains the ladder in prose and lists no special
    // print at all - that is what stops SP Card reading as a scarcity tier.
    expect(rarity?.terms).toEqual([]);
    expect(rarity?.blurb).toContain("Super Rare");
    expect(JSON.stringify(rarity)).not.toContain("SP Card");
  });

  it("says up front that the three can be true at once", () => {
    // Without this a tile badged Super Rare + SP Card + Alt Art reads as a
    // contradiction, which is the whole thing the legend exists to prevent.
    expect(LEGEND_INTRO).toContain("Super Rare");
    expect(LEGEND_INTRO).toContain("SP Card");
    expect(LEGEND_INTRO).toContain("Alt Art");
    expect(LEGEND_INTRO).toMatch(/three different things/);
  });

  it("explains every term the task requires", () => {
    const labels = LEGEND_TERMS.map((term) => term.label);
    for (const required of [
      "Alt Art",
      "Reprint",
      "SP Card",
      "Treasure Rare",
      "Set",
      "Found in",
      "Market Index",
      "Source range",
    ]) {
      expect(labels, `legend is missing ${required}`).toContain(required);
    }
  });

  it("states that Found in is not necessarily the card's origin set", () => {
    const foundIn = LEGEND_TERMS.find((term) => term.label === "Found in");
    expect(foundIn?.definition).toBe(
      "The product this specific printing appeared in. It does not necessarily mean the card originated in that set.",
    );
  });

  it("gives every entry a non-empty definition", () => {
    for (const term of LEGEND_TERMS) {
      expect(term.definition.length).toBeGreaterThan(10);
    }
    for (const section of LEGEND_SECTIONS) {
      if (section.terms.length === 0) {
        expect(section.blurb?.length ?? 0, `${section.title} explains nothing`).toBeGreaterThan(10);
      }
    }
  });
});

describe("getTerm", () => {
  it("resolves static, printing and rarity keys", () => {
    expect(getTerm("identity.found_in")?.label).toBe("Found in");
    expect(getTerm("pricing.market_index")?.label).toBe("Market Index");
    expect(getTerm("pricing.source_range")?.label).toBe("Source range");
    expect(getTerm("printing.alt_art")?.label).toBe("Alt Art");
    expect(getTerm("special_print.sp_card")?.label).toBe("SP Card");
    expect(getTerm("special_print.treasure_rare")?.label).toBe("Treasure Rare");
    expect(getTerm("rarity.sr")?.label).toBe("Super Rare");
  });

  it("returns null for an unknown key so a caller renders nothing", () => {
    expect(getTerm("nope.at.all")).toBeNull();
  });
});
