import type { MetadataRoute } from "next";
import { PUBLIC_INDEXABLE_ROUTES, publicSiteUrl } from "@/lib/publicRoutes";
import { readReleases } from "@/lib/publicServer";
export const dynamic = "force-dynamic";
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const base = publicSiteUrl();
  const releases = await readReleases();
  return [...PUBLIC_INDEXABLE_ROUTES.map((route) => ({ url: route === "/" ? `${base}/` : `${base}${route}` })), ...(releases?.items ?? []).flatMap((release) => [{ url: `${base}/cards?release_product_id=${release.release_product_id}` }, { url: `${base}/analytics?release_product_id=${release.release_product_id}` }])];
}
