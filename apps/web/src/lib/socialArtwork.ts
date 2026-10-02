import "server-only";
import sharp from "sharp";

/** Data-selected approved origins only, bounded body and deadline, no redirects. */
export async function artworkData(url: string | null | undefined): Promise<string | null> {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    const approved = ["https://www.onepiece-cardgame.com", "https://card.yuyu-tei.jp", "https://cdn.snkrdunk.com"];
    if (process.env.R2_PUBLIC_BASE_URL) approved.push(new URL(process.env.R2_PUBLIC_BASE_URL).origin);
    if (parsed.protocol !== "https:" || parsed.username || parsed.password || !approved.includes(parsed.origin)) return null;
    const response = await fetch(parsed, { redirect: "error", next: { revalidate: 86400 }, signal: AbortSignal.timeout(5000) });
    const type = response.headers.get("content-type")?.split(";")[0];
    if (!response.ok || !type || !["image/png", "image/jpeg", "image/webp"].includes(type) || Number(response.headers.get("content-length")) > 8_000_000) return null;
    const reader = response.body?.getReader();
    if (!reader) return null;
    const chunks: Uint8Array[] = [];
    let size = 0;
    for (;;) {
      const next = await reader.read();
      if (next.done) break;
      size += next.value.byteLength;
      if (size > 8_000_000) { await reader.cancel(); return null; }
      chunks.push(next.value);
    }
    const png = await sharp(Buffer.concat(chunks), { limitInputPixels: 20_000_000 }).png().toBuffer();
    return `data:image/png;base64,${png.toString("base64")}`;
  } catch { return null; }
}
