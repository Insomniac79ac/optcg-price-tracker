import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function GET(request: NextRequest) {
  return proxyAdminJson(request, `/admin/price-source-health/gaps${request.nextUrl.search}`, { logLabel: "price-source-health-gaps", timeoutMs: 20_000 });
}
