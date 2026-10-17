import { NextRequest } from "next/server";

import { proxySavedViews } from "@/lib/savedViewsProxy";
import { invalidRouteIdResponse, isNumericRouteId } from "@/lib/routeId";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isNumericRouteId(id)) return invalidRouteIdResponse();
  return proxySavedViews("POST", request, `/saved-views/${id}/use`);
}
