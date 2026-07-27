import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(request: NextRequest) {
  return proxyAdminJson(request, `/admin/snkrdunk-candidates/rematch-all`, { logLabel: "snkrdunk-candidates-rematch-all", timeoutMs: 30_000 });
}
