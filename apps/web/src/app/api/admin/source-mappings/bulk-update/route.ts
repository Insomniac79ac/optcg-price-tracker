import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(request: NextRequest) {
  return proxyAdminJson(request, `/admin/source-mappings/bulk-update`, { logLabel: "source-mappings-bulk-update" });
}
