import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(request: NextRequest) {
  return proxyAdminJson(request, `/admin/actions/run-market-workflow`, { logLabel: "run-market-workflow", timeoutMs: 30_000 });
}
