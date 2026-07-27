import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(request: NextRequest) {
  return proxyAdminJson(request, `/admin/actions/snapshot-market-signals`, { logLabel: "snapshot-market-signals", timeoutMs: 30_000 });
}
