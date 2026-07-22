import { NextRequest } from "next/server";

import { proxySavedViews } from "@/lib/savedViewsProxy";

export async function POST(request: NextRequest) {
  return proxySavedViews("POST", request, "/saved-views/clear-default");
}
