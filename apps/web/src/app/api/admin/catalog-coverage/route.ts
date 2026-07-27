import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function GET(request: NextRequest) {
  return proxyAdminJson(request, `/admin/catalog-coverage${request.nextUrl.search}`, { logLabel: "catalog-coverage", timeoutMs: 30_000 });
}
