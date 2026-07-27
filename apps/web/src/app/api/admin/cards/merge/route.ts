import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(request: NextRequest) {
  return proxyAdminJson(request, `/admin/cards/merge`, { logLabel: "cards-merge", timeoutMs: 30_000 });
}
