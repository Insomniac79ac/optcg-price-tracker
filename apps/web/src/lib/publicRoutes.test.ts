import { describe, expect, it } from "vitest";

import {
  CRAWLER_DISALLOWED_PREFIXES,
  PUBLIC_INDEXABLE_ROUTES,
  publicSiteUrl,
} from "./publicRoutes";
import { FULL_MATCHER, PROTECTED_MATCHER } from "./proxyGuard";

/** "/collection/:path*" -> "/collection" */
const matcherPrefix = (entry: string) => entry.replace(/\/:.*$/, "");

/** Whether Next's matcher would guard `pathname`. ":path*" matches zero or
 * more segments (so it also matches the bare prefix); ":id+" needs at least
 * one, which is exactly what keeps "/cards" public while "/cards/1" is not. */
function isMatched(pathname: string): boolean {
  return FULL_MATCHER.some((entry) => {
    const prefix = matcherPrefix(entry);
    if (entry.includes(":path*")) {
      return pathname === prefix || pathname.startsWith(`${prefix}/`);
    }
    return pathname.startsWith(`${prefix}/`) && pathname.length > prefix.length + 1;
  });
}

describe("public indexable routes", () => {
  it("is exactly the public collector surface", () => {
    expect([...PUBLIC_INDEXABLE_ROUTES]).toEqual(["/", "/cards"]);
  });

  it("never advertises a route that only redirects somewhere else", () => {
    // /market/movers is a temporary redirect into /cards?sort=index_desc
    // (tranche 1A), so it is not a standalone indexable destination.
    expect([...PUBLIC_INDEXABLE_ROUTES]).not.toContain("/market/movers");
  });

  it("still advertises the two pages the public product actually has", () => {
    // Guards against the removal above quietly taking a real page with it.
    expect([...PUBLIC_INDEXABLE_ROUTES]).toContain("/");
    expect([...PUBLIC_INDEXABLE_ROUTES]).toContain("/cards");
  });

  it("never advertises a route the request guard blocks", () => {
    for (const route of PUBLIC_INDEXABLE_ROUTES) {
      expect(isMatched(route), `${route} is advertised but guarded`).toBe(false);
    }
  });

  it("and the guard does block a genuinely private route", () => {
    // Guards the sitemap test above against passing for the wrong reason.
    // /cards/1 is no longer the example: it became public collector surface
    // on 2026-09-01 (see proxyGuard.ts).
    expect(isMatched("/collection")).toBe(true);
    expect(isMatched("/cards/1")).toBe(false);
  });

  it("advertises /cards but never a legacy card-keyed detail URL", () => {
    expect([...PUBLIC_INDEXABLE_ROUTES]).toContain("/cards");
    expect(PUBLIC_INDEXABLE_ROUTES.some((r) => /^\/cards\/.+/.test(r))).toBe(false);
  });
});

describe("crawler disallow list", () => {
  it("covers every guarded route", () => {
    for (const entry of PROTECTED_MATCHER) {
      const prefix = matcherPrefix(entry);
      expect(
        CRAWLER_DISALLOWED_PREFIXES.some((d) => prefix.startsWith(d.replace(/\/$/, ""))),
        `${prefix} is guarded but not disallowed to crawlers`,
      ).toBe(true);
    }
  });

  it("covers admin and the legacy card detail route", () => {
    expect([...CRAWLER_DISALLOWED_PREFIXES]).toContain("/admin");
    expect([...CRAWLER_DISALLOWED_PREFIXES]).toContain("/cards/");
  });

  it("does not disallow the public catalogue itself", () => {
    // "/cards/" must not swallow "/cards" - the trailing slash is what keeps
    // the public catalogue crawlable.
    expect([...CRAWLER_DISALLOWED_PREFIXES]).not.toContain("/cards");
  });

  it("does not block the /market/movers redirect", () => {
    // Dropped from the sitemap, but deliberately still crawlable: a crawler
    // that already knows the URL should be allowed to follow the redirect
    // through to /cards rather than be told the path is off limits.
    for (const disallowed of CRAWLER_DISALLOWED_PREFIXES) {
      expect("/market/movers".startsWith(disallowed)).toBe(false);
    }
  });
});

describe("publicSiteUrl", () => {
  it("prefers NEXT_PUBLIC_SITE_URL and trims trailing slashes", () => {
    const previous = process.env.NEXT_PUBLIC_SITE_URL;
    process.env.NEXT_PUBLIC_SITE_URL = "https://atlas.example.com///";
    expect(publicSiteUrl()).toBe("https://atlas.example.com");
    process.env.NEXT_PUBLIC_SITE_URL = previous;
  });

  it("falls back to an absolute https origin rather than throwing", () => {
    const previous = process.env.NEXT_PUBLIC_SITE_URL;
    delete process.env.NEXT_PUBLIC_SITE_URL;
    expect(publicSiteUrl()).toMatch(/^https:\/\/[^/]+$/);
    process.env.NEXT_PUBLIC_SITE_URL = previous;
  });
});
