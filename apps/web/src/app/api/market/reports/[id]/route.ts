import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

// Admin-only: the backend route requires X-Admin-Token, which proxyAdminJson
// injects server-side after validating an admin session.
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return proxyAdminJson(request, `/market/reports/${encodeURIComponent(id)}`, { logLabel: "market-report-detail" });
}
