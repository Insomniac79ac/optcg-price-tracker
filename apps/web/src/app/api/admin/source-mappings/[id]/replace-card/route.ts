import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return proxyAdminJson(request, `/admin/source-mappings/${id}/replace-card`, { logLabel: "source-mappings-replace-card" });
}
