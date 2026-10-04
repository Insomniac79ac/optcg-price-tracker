import { readFile } from "node:fs/promises";
import path from "node:path";
import { ImageResponse } from "next/og";
import { ShareCard, type ShareCardContent } from "@/lib/shareCard";
import { marketShareContent, printShareContent, publicArtwork } from "@/lib/shareContent";
import { artworkData } from "@/lib/socialArtwork";
import { readCatalogue, readMarket, readPrint, readReleases } from "@/lib/publicServer";
import { releaseLabelEnglish } from "@/lib/releaseNames";
import { selectHeroFanPrints, utcDayKey } from "@/lib/heroFan";
import { toPrintUiModel } from "@/lib/prints";
import { MARKET_VALUE_WINDOWS, type MarketValueWindow } from "@/lib/marketValue";
export const runtime = "nodejs";
const fontData = Promise.all(["LiberationSerif-Bold.ttf", "LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"].map((name) => readFile(path.join(process.cwd(), "src/lib/social-fonts", name))));

async function representativeArt(releaseId: number | null): Promise<string[]> {
  const catalogue = await readCatalogue(`limit=24&sort=created_desc${releaseId === null ? "" : `&release_product_id=${releaseId}`}`);
  const items = (catalogue?.items ?? []).filter((p) => releaseId === null || p.release_product_id === releaseId);
  const chosen = selectHeroFanPrints(items.map(toPrintUiModel), utcDayKey());
  const images = await Promise.all(chosen.map((p) => artworkData(publicArtwork(items.find((item) => item.card_print_id === p.cardPrintId)!))));
  return images.filter((image): image is string => image !== null);
}
export async function GET(request: Request, { params }: { params: Promise<{ kind: string; id: string }> }) {
  const { kind, id } = await params;
  const rawWindow = new URL(request.url).searchParams.get("window") ?? "7d";
  if (!MARKET_VALUE_WINDOWS.includes(rawWindow as MarketValueWindow)) return new Response("Unsupported window", { status: 400 });
  const window = rawWindow as MarketValueWindow;
  const validId = /^[1-9]\d*$/.test(id) && Number.isSafeInteger(Number(id));
  let content: ShareCardContent = { kind: "home", title: "Know your cards. Know the market.", identity: "Track card prices, collection value and the One Piece market.", value: "", context: "", date: "Japanese cards · Prices in JPY" };
  if (kind === "print" && validId) {
    const print = await readPrint(id);
    if (!print || print.card_print_id !== Number(id)) return new Response("Card unavailable", { status: 404 });
    const image = await artworkData(publicArtwork(print));
    content = { ...printShareContent(print), artworks: image ? [image] : [] };
  } else if ((kind === "market" && id === "overall") || (kind === "release" && validId)) {
    const releaseId = kind === "release" ? Number(id) : null;
    const [data, images] = await Promise.all([readMarket(releaseId, window), representativeArt(releaseId)]);
    if (data && data.release_product_id === releaseId && data.scope_kind === (releaseId ? "release" : "overall")) content = marketShareContent(data, window);
    else if (releaseId) {
      const release = (await readReleases())?.items.find((r) => r.release_product_id === releaseId);
      if (!release) return new Response("Release unavailable", { status: 404 });
      content = { kind: "release", code: release.official_code ?? undefined, title: releaseLabelEnglish(release.official_code, release.display_name).replace(`${release.official_code} — `, ""), identity: "Sets on the Move", value: "Value unavailable", context: "Market coverage unavailable", date: "Market history unavailable · Representative release artwork" };
    } else content = { kind: "market", title: "One Piece Market", identity: "", value: "Value unavailable", context: "Market coverage unavailable", date: "Publication unavailable · Representative card artwork" };
    content.artworks = images;
  } else if (kind === "home" && id === "site") content.artworks = await representativeArt(null);
  else return new Response("Not found", { status: 404 });
  const [serif, sans, sansBold] = await fontData;
  return new ImageResponse(<ShareCard content={content} />, { width: 1200, height: 630,
    fonts: [{ name: "Social Serif", data: serif, weight: 700, style: "normal" }, { name: "Social Sans", data: sans, weight: 400, style: "normal" }, { name: "Social Sans", data: sansBold, weight: 700, style: "normal" }],
    headers: { "Cache-Control": "public, max-age=300, s-maxage=300" } });
}
