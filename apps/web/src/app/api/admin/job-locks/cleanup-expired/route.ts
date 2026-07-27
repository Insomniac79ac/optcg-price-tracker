import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(request: NextRequest) {
  return proxyAdminJson(request, `/admin/job-locks/cleanup-expired`, { logLabel: "job-locks-cleanup-expired" });
}
