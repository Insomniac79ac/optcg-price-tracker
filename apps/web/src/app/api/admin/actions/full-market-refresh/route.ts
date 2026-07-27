import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(request: NextRequest) {
  return proxyAdminJson(request, `/admin/actions/full-market-refresh`, { logLabel: "full-market-refresh", timeoutMs: 30_000 });
}
