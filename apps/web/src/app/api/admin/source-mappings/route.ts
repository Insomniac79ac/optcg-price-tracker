import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function GET(request: NextRequest) {
  return proxyAdminJson(request, `/admin/source-mappings${request.nextUrl.search}`, { logLabel: "source-mappings" });
}
