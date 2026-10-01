import MarketClient from "./MarketClient";
import { readMarket } from "@/lib/publicServer";
import { pageMetadata, searchParamsUrl, type PublicSearchParams } from "@/lib/publicSeo";
import { parseMarketRelease, MARKET_VALUE_WINDOWS, type MarketValueWindow } from "@/lib/marketValue";
import { releaseLabelEnglish } from "@/lib/releaseNames";
type Props = { searchParams: Promise<PublicSearchParams> };
export async function generateMetadata({ searchParams }: Props) {
  const query = searchParamsUrl(await searchParams);
  const id = parseMarketRelease(query.get("release_product_id"));
  const rawWindow = query.get("window");
  const window: MarketValueWindow = MARKET_VALUE_WINDOWS.includes(rawWindow as MarketValueWindow) ? rawWindow as MarketValueWindow : "7d";
  const data = id === "invalid" ? null : await readMarket(id, window);
  const name = data?.scope_kind === "release" ? releaseLabelEnglish(data.release_code, data.release_name) : "One Piece";
  return pageMetadata(`${name} Card Market`, `Follow ${name} price movement and partial tracked Market Value in JPY, with pricing coverage shown alongside the figures.`, typeof id === "number" ? `/analytics?release_product_id=${id}` : "/analytics", typeof id === "number" ? `/share/release/${id}?window=${window}` : `/share/market/overall?window=${window}`, id !== "invalid" && (id === null || !!data));
}
export default async function MarketPage({ searchParams }: Props) {
  const query = searchParamsUrl(await searchParams);
  const id = parseMarketRelease(query.get("release_product_id"));
  const rawWindow = query.get("window");
  const window: MarketValueWindow = MARKET_VALUE_WINDOWS.includes(rawWindow as MarketValueWindow) ? rawWindow as MarketValueWindow : "7d";
  const data = id === "invalid" ? null : await readMarket(id, window);
  return <MarketClient initialData={data} />;
}
