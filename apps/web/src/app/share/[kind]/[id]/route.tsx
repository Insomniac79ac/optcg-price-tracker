import sharp from "sharp";
import { ImageResponse } from "next/og";
import { ShareCard, type ShareCardContent } from "@/lib/shareCard";
import { marketShareContent, printShareContent } from "@/lib/shareContent";
import { readCatalogue, readMarket, readPrint, readReleases } from "@/lib/publicServer";
import { releaseLabelEnglish } from "@/lib/releaseNames";
export const runtime = "nodejs";

async function artworkData(url: string | null | undefined): Promise<string | null> {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    const approved = ["https://www.onepiece-cardgame.com", "https://card.yuyu-tei.jp", "https://cdn.snkrdunk.com"];
    if (process.env.R2_PUBLIC_BASE_URL) approved.push(new URL(process.env.R2_PUBLIC_BASE_URL).origin);
    if (!approved.includes(parsed.origin)) return null;
    const response = await fetch(url, { redirect: "error", next: { revalidate: 86400 }, signal: AbortSignal.timeout(5000) });
    const type = response.headers.get("content-type")?.split(";")[0];
    if (!response.ok || !type || !["image/png", "image/jpeg", "image/webp"].includes(type) || Number(response.headers.get("content-length")) > 8_000_000) return null;
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength > 8_000_000) return null;
    const png = await sharp(Buffer.from(bytes), { limitInputPixels: 20_000_000 }).png().toBuffer();
    return `data:image/png;base64,${png.toString("base64")}`;
  } catch { return null; }
}
export async function GET(_request: Request, { params }: { params: Promise<{ kind: string; id: string }> }) {
  const { kind, id } = await params;
  let content: ShareCardContent = { kind: "home", title: "Know what your cards are actually worth.", identity: "Price context for the cards you own or want.", value: "", context: "Japanese card prices and One Piece market movement", date: "Card prices · Collection value · Market context" };
  if (kind === "print" && /^\d+$/.test(id)) {
    const print = await readPrint(id);
    if (!print) return new Response("Card unavailable", { status: 404 });
    content = { ...printShareContent(print), artwork: await artworkData(print.display_image?.url || print.image_url) };
  } else if ((kind === "market" && id === "overall") || (kind === "release" && /^\d+$/.test(id))) {
    const releaseId = kind === "release" ? Number(id) : null;
    const data = await readMarket(releaseId);
    if (data) content = marketShareContent(data);
    else if (releaseId) {
      const release = (await readReleases())?.items.find((r) => r.release_product_id === releaseId);
      if (!release) return new Response("Release unavailable", { status: 404 });
      content = { kind: "release", title: releaseLabelEnglish(release.official_code, release.display_name), identity: `Release ${releaseId}`, value: "Value unavailable", context: "Compare prices for the exact printings in this release", date: "Market history unavailable" };
    } else content = { kind: "market", title: "One Piece card market", identity: "Japanese physical printings", value: "Value unavailable", context: "Market data could not be loaded", date: "Try again for the latest published figures" };
    // Catalogue membership is explicit. The image is representative of the release,
    // not a claim that this printing contributed to the market basket.
    if (releaseId) {
      const print = (await readCatalogue(`release_product_id=${releaseId}&limit=1&sort=index_desc`))?.items[0];
      content.artwork = await artworkData(print?.display_image?.url || print?.image_url);
      if (content.artwork) content.date += " · Release artwork";
    }
  } else if (kind !== "home" || id !== "site") return new Response("Not found", { status: 404 });
  return new ImageResponse(<ShareCard content={content} />, { width: 1200, height: 630, headers: { "Cache-Control": "public, max-age=300, s-maxage=300" } });
}
