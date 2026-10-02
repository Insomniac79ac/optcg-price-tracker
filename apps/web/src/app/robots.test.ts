import { expect, it, vi } from "vitest";
vi.mock("./prints/sitemap", () => ({ generateSitemaps: async () => [{ id: 0 }, { id: 1 }] }));
import robots from "./robots";
import { CRAWLER_DISALLOWED_PREFIXES } from "@/lib/publicRoutes";
it("allows search while preserving GPTBot's previous effective access and private exclusions", async () => {
  const data = await robots();
  expect(data.rules).toEqual([
    { userAgent: "*", allow: ["/", "/api/card-image"], disallow: [...CRAWLER_DISALLOWED_PREFIXES] },
    { userAgent: "GPTBot", allow: "/", disallow: [...CRAWLER_DISALLOWED_PREFIXES] },
  ]);
  expect(data.sitemap).toEqual(expect.arrayContaining([expect.stringMatching(/\/prints\/sitemap\/1.xml$/)]));
});
