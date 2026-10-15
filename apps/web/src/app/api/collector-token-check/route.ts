import { NextResponse } from "next/server";

import { cachedCollectorTokenCheck, tokenCheckClientKey, tokenCheckRetryAfter } from "@/lib/collectorTokenCheck";

// Read by scripts/verify_staging_delivery.py. Public on purpose: it reports
// one word, holds no session, and its probe pass cannot open any account.
// The answer is reused for 60 s and each client is rate limited, so the
// route cannot be used to make the website hammer the API.
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const retryAfter = tokenCheckRetryAfter(tokenCheckClientKey(request.headers));
  if (retryAfter !== null) {
    return NextResponse.json(
      { error: "Too many requests" },
      { status: 429, headers: { "Cache-Control": "no-store", "Retry-After": String(retryAfter) } },
    );
  }
  const status = await cachedCollectorTokenCheck();
  return NextResponse.json({ status }, { headers: { "Cache-Control": "no-store" } });
}
