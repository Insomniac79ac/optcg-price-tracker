import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

// Distinct from the sibling [id]/* and rematch-all routes in this
// directory, which proxy to the backend's /admin/snkrdunk-candidates/*
// router (app.api.admin_snkrdunk_matching) - this one proxies to the
// older /snkrdunk/candidates router (app.api.snkrdunk_candidates), which
// is where the list/match/reject endpoints live. Both backend routers
// require X-Admin-Token; both are fronted by this same Next.js route
// group for a consistent same-origin, session-authorized surface.
export async function GET(request: NextRequest) {
  return proxyAdminJson(request, `/snkrdunk/candidates${request.nextUrl.search}`, {
    logLabel: "snkrdunk-candidates-list",
  });
}
