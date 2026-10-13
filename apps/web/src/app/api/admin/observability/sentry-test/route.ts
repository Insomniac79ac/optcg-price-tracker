import { NextRequest } from "next/server";

import { proxyAdminJson, requireAdminOrResponse } from "@/lib/adminProxy";

export const dynamic = "force-dynamic";

/** Fails on purpose so an operator can confirm error tracking reaches Sentry
 * (Collector v1 S2). Admin session only; reads and writes nothing.
 *   ?target=web  throws here (captured by instrumentation.ts onRequestError)
 *   ?target=api  asks the API to raise (captured by its Sentry SDK) */
export async function GET(request: NextRequest) {
  const target = request.nextUrl.searchParams.get("target");
  if (target === "api") {
    return proxyAdminJson(request, "/admin/observability/sentry-test", { logLabel: "sentry-test" });
  }
  const auth = await requireAdminOrResponse();
  if ("response" in auth) return auth.response;
  throw new Error("Deliberate Sentry test error (web). Safe to ignore.");
}
