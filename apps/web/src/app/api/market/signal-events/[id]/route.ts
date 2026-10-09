import { NextRequest } from "next/server";

import { proxyAdminJson } from "@/lib/adminProxy";

// Admin-only: the backend route requires X-Admin-Token, which proxyAdminJson
// injects server-side after validating an admin session.
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return proxyAdminJson(request, `/market/signal-events/${encodeURIComponent(id)}`, {
    logLabel: "signal-event-patch",
  });
}
