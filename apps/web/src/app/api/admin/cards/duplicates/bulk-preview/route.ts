import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(request: NextRequest) {
  return proxyAdminJson(request, `/admin/cards/duplicates/bulk-preview`, { logLabel: "cards-duplicates-bulk-preview", timeoutMs: 30_000 });
}
