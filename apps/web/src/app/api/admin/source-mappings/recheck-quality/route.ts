import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(request: NextRequest) {
  return proxyAdminJson(request, `/admin/source-mappings/recheck-quality`, { logLabel: "source-mappings-recheck-quality", timeoutMs: 30_000 });
}
