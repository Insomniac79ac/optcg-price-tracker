import { NextResponse } from "next/server";

import { checkCollectorToken } from "@/lib/collectorTokenCheck";

// Read by scripts/verify_staging_delivery.py. Public on purpose: it reports
// one word, holds no session, and its probe pass cannot open any account.
export const dynamic = "force-dynamic";

export async function GET() {
  const status = await checkCollectorToken();
  if (status !== "ok") console.error(`[collector token check] ${status}`);
  return NextResponse.json({ status }, { headers: { "Cache-Control": "no-store" } });
}
