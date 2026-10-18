import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";
import { invalidRouteIdResponse, isNumericRouteId } from "@/lib/routeId";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  if (!isNumericRouteId(id)) return invalidRouteIdResponse();
  return proxyAdminJson(request, `/admin/snkrdunk-candidates/${id}/approve-match`, { logLabel: "snkrdunk-candidates-approve-match" });
}
