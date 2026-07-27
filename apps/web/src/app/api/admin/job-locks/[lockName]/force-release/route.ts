import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ lockName: string }> },
) {
  const { lockName } = await params;
  return proxyAdminJson(request, `/admin/job-locks/${lockName}/force-release`, { logLabel: "job-locks-force-release" });
}
