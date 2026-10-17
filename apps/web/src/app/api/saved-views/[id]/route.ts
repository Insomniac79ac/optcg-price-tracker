import { NextRequest } from "next/server";

import { proxySavedViews } from "@/lib/savedViewsProxy";
import { invalidRouteIdResponse, isNumericRouteId } from "@/lib/routeId";

export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isNumericRouteId(id)) return invalidRouteIdResponse();
  return proxySavedViews("GET", request, `/saved-views/${id}`);
}

export async function PATCH(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isNumericRouteId(id)) return invalidRouteIdResponse();
  return proxySavedViews("PATCH", request, `/saved-views/${id}`);
}

export async function DELETE(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isNumericRouteId(id)) return invalidRouteIdResponse();
  return proxySavedViews("DELETE", request, `/saved-views/${id}`);
}
