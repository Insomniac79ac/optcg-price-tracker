import type { NextRequest } from "next/server";

import { proxyMe } from "@/lib/meProxy";

// Collector requests from the browser (PLAN §D1): same-origin, cookie
// session only. The API token is minted and spent on the server; see
// src/lib/collectorApi.ts.
type Context = { params: Promise<{ path?: string[] }> };

async function handle(request: NextRequest, { params }: Context) {
  return proxyMe(request, (await params).path);
}

export const dynamic = "force-dynamic";
export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
