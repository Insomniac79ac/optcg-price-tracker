import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function GET(request: NextRequest) {
  return proxyAdminJson(
    request,
    `/admin/source-mapping-proposals/review/releases${request.nextUrl.search}`,
    { logLabel: "source-mapping-proposal-review-releases" },
  );
}
