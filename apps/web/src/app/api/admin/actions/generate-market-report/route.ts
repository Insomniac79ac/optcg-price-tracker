import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(request: NextRequest) {
  return proxyAdminJson(request, `/admin/actions/generate-market-report`, { logLabel: "generate-market-report", timeoutMs: 30_000 });
}
