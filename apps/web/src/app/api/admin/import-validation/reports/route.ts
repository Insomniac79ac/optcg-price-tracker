import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function GET(request: NextRequest) {
  return proxyAdminJson(request, `/admin/import-validation/reports${request.nextUrl.search}`, { logLabel: "import-validation-reports" });
}
