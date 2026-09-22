import { NextRequest } from "next/server";

import { proxyAdminActorJson } from "@/lib/adminProxy";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return proxyAdminActorJson(
    request,
    `/admin/source-mapping-proposals/review/groups/${encodeURIComponent(id)}/approve-exact`,
    { logLabel: "source-mapping-proposal-approve-exact" },
  );
}
