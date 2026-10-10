import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

// Admin-only: the backend route requires X-Admin-Token, which proxyAdminJson
// injects server-side after validating an admin session.
export async function GET(request: NextRequest) {
  return proxyAdminJson(request, `/analytics/digest/latest${request.nextUrl.search}`, { logLabel: "analytics-digest-latest" });
}
