import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function GET(request: NextRequest) {
  return proxyAdminJson(request, `/admin/catalog-coverage/gaps${request.nextUrl.search}`, { logLabel: "catalog-coverage-gaps", timeoutMs: 20_000 });
}
