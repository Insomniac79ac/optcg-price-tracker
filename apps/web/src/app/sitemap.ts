import type { MetadataRoute } from "next";

import { PUBLIC_INDEXABLE_ROUTES, publicSiteUrl } from "@/lib/publicRoutes";

// Next.js serves this at /sitemap.xml. Only the stable, parameter-free public
// collector routes - see PUBLIC_INDEXABLE_ROUTES for why print detail pages
// are left to be crawled from /cards rather than enumerated here.
export default function sitemap(): MetadataRoute.Sitemap {
  const base = publicSiteUrl();
  return PUBLIC_INDEXABLE_ROUTES.map((route) => ({
    url: route === "/" ? `${base}/` : `${base}${route}`,
    changeFrequency: "daily" as const,
    priority: route === "/" ? 1 : 0.8,
  }));
}
