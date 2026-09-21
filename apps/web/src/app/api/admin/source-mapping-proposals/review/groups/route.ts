import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function GET(request: NextRequest) {
  return proxyAdminJson(
    request,
    `/admin/source-mapping-proposals/review/groups${request.nextUrl.search}`,
    { logLabel: "source-mapping-proposal-review-groups" },
  );
}
