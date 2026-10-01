import Link from "next/link";
import CardsClient from "./CardsClient";
import { JsonLd } from "@/components/JsonLd";
import { buildCatalogueQuery, catalogueParams, parseCatalogueState, resolveLegacyRelease } from "@/lib/catalogueState";
import { readCatalogue, readReleases } from "@/lib/publicServer";
import { breadcrumbs, pageMetadata, searchParamsUrl, type PublicSearchParams } from "@/lib/publicSeo";
import { releaseLabelEnglish } from "@/lib/releaseNames";
type Props = { searchParams: Promise<PublicSearchParams> };
export async function generateMetadata({ searchParams }: Props) {
  const query = searchParamsUrl(await searchParams);
  const releases = await readReleases();
  const { filters } = parseCatalogueState(query);
  const selected = resolveLegacyRelease(filters, releases?.items ?? []);
  const release = releases?.items.find((r) => r.release_product_id === selected.releaseProductId);
  const path = release ? `/cards?release_product_id=${release.release_product_id}` : "/cards";
  const name = release ? releaseLabelEnglish(release.official_code, release.display_name) : "One Piece";
  const index = ![...query.keys()].some((k) => !["release_product_id", "set"].includes(k)) && (!query.has("release_product_id") || !!release);
  return pageMetadata(`${name} Card Prices`, `Find ${name} cards and compare Japanese source prices for each exact printing. Unpriced cards are shown as unavailable.`, path, release ? `/share/release/${release.release_product_id}` : undefined, index);
}
export default async function CardsPage({ searchParams }: Props) {
  const query = searchParamsUrl(await searchParams);
  const releases = await readReleases();
  const parsed = parseCatalogueState(query);
  const filters = resolveLegacyRelease(parsed.filters, releases?.items ?? []);
  const apiQuery = new URLSearchParams({ limit: "24", offset: String(parsed.offset) });
  for (const [key, value] of Object.entries(catalogueParams(filters))) for (const item of Array.isArray(value) ? value : value === undefined ? [] : [value]) apiQuery.append(key, String(item));
  const data = await readCatalogue(apiQuery.toString());
  const seed = { query: buildCatalogueQuery(filters, parsed.offset), data };
  const release = releases?.items.find((r) => r.release_product_id === filters.releaseProductId);
  const name = release ? releaseLabelEnglish(release.official_code, release.display_name) : "Card Prices";
  return <><JsonLd data={breadcrumbs([{ name: "Home", path: "/" }, { name, path: release ? `/cards?release_product_id=${release.release_product_id}` : "/cards" }])} /><CardsClient initialReleases={releases} seed={seed} />
    {data?.pagination.has_next && <nav aria-label="More card prices" className="mx-auto max-w-6xl px-6 pb-8"><Link href={`/cards${buildCatalogueQuery(filters, data.pagination.next_offset ?? parsed.offset + 24)}`} prefetch={false}>Next page of card prices →</Link></nav>}
  </>;
}
