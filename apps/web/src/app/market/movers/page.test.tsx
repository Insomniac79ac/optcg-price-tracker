import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it, vi } from "vitest";

const { redirect } = vi.hoisted(() => ({ redirect: vi.fn() }));
vi.mock("next/navigation", () => ({ redirect }));

import MarketMoversPage, { MARKET_MOVERS_REDIRECT } from "./page";

/** /market/movers is parked, not deleted (tranche 1A, 2026-08-19). These
 * tests pin the two things that make it parked rather than gone: it answers
 * a *temporary* redirect, and it holds no catalogue of its own. */
describe("/market/movers", () => {
  it("redirects to the catalogue sorted by Market Index", () => {
    MarketMoversPage();

    expect(redirect).toHaveBeenCalledWith("/cards?sort=index_desc");
    expect(MARKET_MOVERS_REDIRECT).toBe("/cards?sort=index_desc");
  });

  it("redirects temporarily, never permanently", () => {
    // next/navigation's redirect() answers 307; permanentRedirect() answers
    // 308 and would be cached in every visitor's browser. This route is
    // expected back once there is real price history to show movement from,
    // so a 308 would be actively in the way.
    const source = readFileSync(path.join(__dirname, "page.tsx"), "utf-8");
    expect(source).toMatch(/\bredirect\(/);
    expect(source).not.toMatch(/permanentRedirect/);
  });

  it("keeps no second public catalogue surface alive here", () => {
    const source = readFileSync(path.join(__dirname, "page.tsx"), "utf-8");
    for (const forbidden of [
      "fetchPrintCatalogue",
      "fetchCardsCatalogue",
      "PrintCardTile",
      "CardGrid",
      "useState",
    ]) {
      expect(source).not.toContain(forbidden);
    }
  });
});
