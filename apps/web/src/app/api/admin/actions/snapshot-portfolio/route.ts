import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(request: NextRequest) {
  return proxyAdminJson(request, `/admin/actions/snapshot-portfolio`, { logLabel: "snapshot-portfolio", timeoutMs: 30_000 });
}
