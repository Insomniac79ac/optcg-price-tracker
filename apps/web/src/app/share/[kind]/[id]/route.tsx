import { readFile } from "node:fs/promises";
import path from "node:path";
import { MARKET_VALUE_WINDOWS, type MarketValueWindow } from "@/lib/marketValue";
export const runtime = "nodejs";

// Static fallback while Next.js is on 16.2.x (owner decision 2026-10-16).
// GHSA-vcvr-r3jv-pc5j (RCE in next/og ImageResponse) is fixed only in 16.3.6+,
// and 16.3.x does not pass staging verification yet, so every share URL serves
// one fixed card instead of rendering with next/og. The per-page cards
// (lib/shareCard.tsx, lib/shareContent.ts) stay in the tree; restore the
// ImageResponse route from git history once Next.js is on 16.3.6 or later.
// The same URLs still answer, so page metadata needs no change.
const fallback = readFile(path.join(process.cwd(), "public/brand/share-fallback.png"));

export async function GET(request: Request, { params }: { params: Promise<{ kind: string; id: string }> }) {
  const { kind, id } = await params;
  const rawWindow = new URL(request.url).searchParams.get("window") ?? "7d";
  if (!MARKET_VALUE_WINDOWS.includes(rawWindow as MarketValueWindow)) return new Response("Unsupported window", { status: 400 });
  const validId = /^[1-9]\d*$/.test(id) && Number.isSafeInteger(Number(id));
  const known = ((kind === "print" || kind === "release") && validId) || (kind === "market" && id === "overall") || (kind === "home" && id === "site");
  if (!known) return new Response("Not found", { status: 404 });
  return new Response(new Uint8Array(await fallback), { headers: { "Content-Type": "image/png", "Cache-Control": "public, max-age=300, s-maxage=300" } });
}
