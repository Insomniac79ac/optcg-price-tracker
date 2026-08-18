import type { MetadataRoute } from "next";

import { CRAWLER_DISALLOWED_PREFIXES, publicSiteUrl } from "@/lib/publicRoutes";

// Next.js serves this at /robots.txt. Before it existed that path 404'd,
// which is harmless but leaves crawlers to discover the private and internal
// routes for themselves.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: [...CRAWLER_DISALLOWED_PREFIXES],
    },
    sitemap: `${publicSiteUrl()}/sitemap.xml`,
  };
}
