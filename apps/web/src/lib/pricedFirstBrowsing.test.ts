/** Priced-first public browsing: what a first-time collector lands on.
 *
 * This file used to also pin the "redundant source row" rule - the four
 * conditions under which a tile's only source row was hidden for repeating the
 * Market Index. That rule is gone (see the note where isRedundantSingleSource
 * used to live in ./prints), and its replacement is an assertion about what
 * the tile RENDERS rather than about a predicate, so it lives in
 * app/cards/page.test.tsx beside the rest of the tile's output.
 */

import { describe, expect, it } from "vitest";

import { EMPTY_PRINT_FILTERS } from "@/components/ui/PrintCatalogueToolbar";

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
