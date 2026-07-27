import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(request: NextRequest) {
  return proxyAdminJson(request, `/admin/actions/generate-analytics-digest`, { logLabel: "generate-analytics-digest", timeoutMs: 30_000 });
}
