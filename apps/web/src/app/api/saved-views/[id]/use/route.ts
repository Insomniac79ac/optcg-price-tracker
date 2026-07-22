import { NextRequest } from "next/server";

import { proxySavedViews } from "@/lib/savedViewsProxy";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return proxySavedViews("POST", request, `/saved-views/${id}/use`);
}
