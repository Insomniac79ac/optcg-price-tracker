import { NextRequest } from "next/server";

import { proxySavedViews } from "@/lib/savedViewsProxy";

export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return proxySavedViews("GET", request, `/saved-views/${id}`);
}

export async function PATCH(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return proxySavedViews("PATCH", request, `/saved-views/${id}`);
}

export async function DELETE(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return proxySavedViews("DELETE", request, `/saved-views/${id}`);
}
