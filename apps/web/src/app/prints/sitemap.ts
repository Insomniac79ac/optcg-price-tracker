import type { MetadataRoute } from "next";
import { readCatalogue } from "@/lib/publicServer";
import { absoluteUrl } from "@/lib/publicSeo";
export const dynamic = "force-dynamic";
// Each shard uses one bounded public catalogue request, in the API’s deterministic card-code order.
export async function generateSitemaps() {
  const catalogue = await readCatalogue("limit=1&sort=card_code");
  return Array.from({ length: Math.ceil((catalogue?.total ?? 0) / 100) }, (_, id) => ({ id }));
}
export default async function sitemap({ id }: { id: Promise<string> }): Promise<MetadataRoute.Sitemap> {
  const shard = Number(await id);
  if (!Number.isSafeInteger(shard) || shard < 0) return [];
  const catalogue = await readCatalogue(`limit=100&offset=${shard * 100}&sort=card_code`);
  return (catalogue?.items ?? []).map((print) => ({ url: absoluteUrl(`/prints/${print.card_print_id}`) }));
}
