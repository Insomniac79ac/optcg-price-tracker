import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function GET(request: NextRequest) {
  return proxyAdminJson(request, `/admin/market-workflow-runs${request.nextUrl.search}`, { logLabel: "market-workflow-runs", timeoutMs: 30_000 });
}
