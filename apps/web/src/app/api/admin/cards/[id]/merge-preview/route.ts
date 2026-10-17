import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";
import { invalidRouteIdResponse, isNumericRouteId } from "@/lib/routeId";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  if (!isNumericRouteId(id)) return invalidRouteIdResponse();
  return proxyAdminJson(request, `/admin/cards/${id}/merge-preview${request.nextUrl.search}`, { logLabel: "cards-merge-preview" });
}
