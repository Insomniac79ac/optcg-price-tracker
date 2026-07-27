import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return proxyAdminJson(request, `/admin/alert-rules/${id}`, {
    logLabel: "admin-alert-rule-update",
  });
}
