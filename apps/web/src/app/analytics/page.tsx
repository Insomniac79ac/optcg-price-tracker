import MarketClient from "./MarketClient";
import { readMarket } from "@/lib/publicServer";
import { pageMetadata, searchParamsUrl, type PublicSearchParams } from "@/lib/publicSeo";
import { parseMarketRelease } from "@/lib/marketValue";
import { releaseLabelEnglish } from "@/lib/releaseNames";
type Props = { searchParams: Promise<PublicSearchParams> };
export async function generateMetadata({ searchParams }: Props) {
  const query = searchParamsUrl(await searchParams);
  const id = parseMarketRelease(query.get("release_product_id"));
  const data = id === "invalid" ? null : await readMarket(id);
  const name = data?.scope_kind === "release" ? releaseLabelEnglish(data.release_code, data.release_name) : "One Piece";
  return pageMetadata(`${name} Card Market`, `Follow ${name} price movement and partial tracked Market Value in JPY, with pricing coverage shown alongside the figures.`, typeof id === "number" ? `/analytics?release_product_id=${id}` : "/analytics", typeof id === "number" ? `/share/release/${id}` : "/share/market/overall", id !== "invalid" && (id === null || !!data));
}
export default async function MarketPage({ searchParams }: Props) {
  const id = parseMarketRelease(searchParamsUrl(await searchParams).get("release_product_id"));
  const data = id === "invalid" ? null : await readMarket(id);
  return <MarketClient initialData={data} />;
}
