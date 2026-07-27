import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(request: NextRequest) {
  return proxyAdminJson(request, `/admin/actions/send-market-report-digest`, { logLabel: "send-market-report-digest", timeoutMs: 30_000 });
}
