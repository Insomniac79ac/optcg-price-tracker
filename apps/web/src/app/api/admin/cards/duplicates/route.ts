import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function GET(request: NextRequest) {
  return proxyAdminJson(request, `/admin/cards/duplicates${request.nextUrl.search}`, { logLabel: "cards-duplicates", timeoutMs: 30_000 });
}
