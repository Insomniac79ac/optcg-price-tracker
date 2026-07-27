import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function GET(request: NextRequest) {
  return proxyAdminJson(request, `/admin/alert-events${request.nextUrl.search}`, {
    logLabel: "admin-alert-events",
  });
}
