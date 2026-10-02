import type { MetadataRoute } from "next";
import { CRAWLER_DISALLOWED_PREFIXES, publicSiteUrl } from "@/lib/publicRoutes";
import { generateSitemaps } from "./prints/sitemap";
export const dynamic = "force-dynamic";
export default async function robots(): Promise<MetadataRoute.Robots> {
  const base = publicSiteUrl();
  // Wildcard allows OAI-SearchBot. Keep GPTBot’s previous effective rules
  // verbatim: the artwork-proxy search exception must not expand training access.
  return { rules: [{ userAgent: "*", allow: ["/", "/api/card-image"], disallow: [...CRAWLER_DISALLOWED_PREFIXES] }, { userAgent: "GPTBot", allow: "/", disallow: [...CRAWLER_DISALLOWED_PREFIXES] }], sitemap: [`${base}/sitemap.xml`, ...(await generateSitemaps()).map(({ id }) => `${base}/prints/sitemap/${id}.xml`)] };
}
