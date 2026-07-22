import { NextRequest } from "next/server";

import { proxySavedViews } from "@/lib/savedViewsProxy";

export async function GET(request: NextRequest) {
  return proxySavedViews("GET", request, "/saved-views");
}

export async function POST(request: NextRequest) {
  return proxySavedViews("POST", request, "/saved-views");
}
