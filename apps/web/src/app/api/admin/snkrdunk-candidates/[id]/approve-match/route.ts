import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return proxyAdminJson(request, `/admin/snkrdunk-candidates/${id}/approve-match`, { logLabel: "snkrdunk-candidates-approve-match" });
}
