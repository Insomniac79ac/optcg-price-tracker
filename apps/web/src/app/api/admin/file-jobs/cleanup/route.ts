import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(request: NextRequest) {
  return proxyAdminJson(request, `/admin/file-jobs/cleanup`, { logLabel: "file-jobs-cleanup" });
}
