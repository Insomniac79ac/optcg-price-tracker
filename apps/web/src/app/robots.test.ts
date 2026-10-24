import { afterEach, expect, it, vi } from "vitest";
vi.mock("./prints/sitemap", () => ({ generateSitemaps: async () => [{ id: 0 }, { id: 1 }] }));
import robots from "./robots";
import { CRAWLER_DISALLOWED_PREFIXES } from "@/lib/publicRoutes";
afterEach(() => vi.unstubAllEnvs());
it("with indexing on, allows search while preserving GPTBot's previous effective access and private exclusions", async () => {
  vi.stubEnv("SITE_SEARCH_INDEXING", "on");
  const data = await robots();
  expect(data.rules).toEqual([
    { userAgent: "*", allow: ["/", "/api/card-image"], disallow: [...CRAWLER_DISALLOWED_PREFIXES] },
    { userAgent: "GPTBot", allow: "/", disallow: [...CRAWLER_DISALLOWED_PREFIXES] },
  ]);
  expect(data.sitemap).toEqual(expect.arrayContaining([expect.stringMatching(/\/prints\/sitemap\/1.xml$/)]));
});
it("with indexing off (default), lists no sitemap and leaves crawling open so noindex is read", async () => {
  for (const value of [undefined, "", "off", "ON", "true"]) {
    vi.stubEnv("SITE_SEARCH_INDEXING", value as string);
    const data = await robots();
    expect(data).toEqual({ rules: [{ userAgent: "*", allow: "/" }] });
  }
});
