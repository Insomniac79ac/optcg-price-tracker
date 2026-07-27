import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return proxyAdminJson(request, `/admin/market-workflow-runs/${id}`, { logLabel: "market-workflow-run-detail", timeoutMs: 30_000 });
}
