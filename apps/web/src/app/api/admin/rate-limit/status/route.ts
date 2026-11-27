import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

// Admin-only read of the API's rate-limit status counts. Never cached.
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  return proxyAdminJson(request, "/admin/rate-limit/status", { logLabel: "rate-limit-status" });
}
