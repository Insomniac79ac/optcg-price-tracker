import { createRequire } from "node:module";

import { describe, expect, it } from "vitest";

import config from "../../next.config";
import { legacyRedirects } from "./legacyRedirects";

// The same matcher Next.js uses for next.config.ts redirect sources.
const { pathToRegexp } = createRequire(import.meta.url)("next/dist/compiled/path-to-regexp") as {
  pathToRegexp: (source: string) => RegExp;
};
const matches = (source: string, path: string) => pathToRegexp(source).test(path);

const EXPECTED: Array<[string, string]> = [
  ["/analytics/buy-decisions", "/collection"],
  ["/analytics/sell-decisions", "/collection"],
  ["/analytics/portfolio-risk", "/collection"],
  ["/analytics/grading", "/collection"],
  ["/analytics/digest", "/collection"],
  ["/dashboard", "/collection"],
  ["/activity", "/collection"],
  ["/market/signals", "/analytics"],
  ["/market/signal-events", "/analytics"],
  ["/market/opportunities", "/analytics"],
  ["/market/report", "/analytics"],
  ["/search", "/cards"],
  ["/collection/vault", "/collection"],
  ["/analytics/collection", "/collection"],
  ["/wishlist", "/watchlist"],
  ["/analytics/wishlist", "/watchlist"],
];

describe("Collector v1 S1 and S8 legacy redirects", () => {
  it("is exactly the PLAN §F table, every entry permanent (308)", () => {
    expect(legacyRedirects()).toEqual(
      EXPECTED.map(([from, destination]) => ({ source: `${from}/:path*`, destination, permanent: true })),
    );
  });

  it("is what next.config.ts serves", async () => {
    const redirects = await config("phase-test").redirects!();
    expect(redirects).toEqual(legacyRedirects());
  });

  it("matches the bare page and its subpaths", () => {
    for (const [from] of EXPECTED) {
      expect(matches(`${from}/:path*`, from), from).toBe(true);
      expect(matches(`${from}/:path*`, `${from}/x/y`), `${from}/x/y`).toBe(true);
    }
    expect(matches("/market/report/:path*", "/market/reports")).toBe(false);
  });

  it("leaves /grading, the admin run history and every kept page unredirected (404 or served)", () => {
    const sources = legacyRedirects().map((r) => r.source);
    for (const kept of ["/grading", "/admin/market-workflow-runs", "/analytics", "/collection", "/watchlist",
      "/account", "/market/movers", "/cards", "/prints/1", "/analytics/market"]) {
      expect(sources.some((s) => matches(s, kept)), kept).toBe(false);
    }
  });

  it("sends every old path to exactly one target, and never into another redirect", () => {
    const redirects = legacyRedirects();
    for (const [from] of EXPECTED) {
      for (const path of [from, `${from}/x`]) {
        expect(redirects.filter((r) => matches(r.source, path)), path).toHaveLength(1);
      }
    }
    for (const { destination } of redirects) {
      expect(redirects.some((r) => matches(r.source, destination)), destination).toBe(false);
    }
  });
});
