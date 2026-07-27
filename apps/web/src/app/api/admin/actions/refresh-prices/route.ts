import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(request: NextRequest) {
  return proxyAdminJson(request, `/admin/actions/refresh-prices`, { logLabel: "refresh-prices", timeoutMs: 30_000 });
}
