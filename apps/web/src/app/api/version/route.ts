import { NextResponse } from "next/server";

import { buildVersion } from "@/generated/buildVersion";

// Server-side only - never exposed to the browser bundle (not NEXT_PUBLIC_*).
// Same reasoning as src/app/api/backend-health/route.ts.
const API_INTERNAL_URL = process.env.API_INTERNAL_URL || "http://api:8000";
const BACKEND_TIMEOUT_MS = 5_000;

function getWebVersionInfo() {
  return {
    version: process.env.APP_VERSION || buildVersion,
    git_commit: process.env.GIT_COMMIT || process.env.VERCEL_GIT_COMMIT_SHA || "unknown",
    build_time: process.env.BUILD_TIME || "unknown",
  };
}

export async function GET() {
  const web = getWebVersionInfo();

  let api: { version: string; git_commit: string } | null = null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_INTERNAL_URL}/version`, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (res.ok) {
      const body = await res.json();
      api = { version: body.version, git_commit: body.git_commit };
    }
  } catch (err) {
    console.error(`[version route] failed to reach backend at ${API_INTERNAL_URL}/version: ${err}`);
  } finally {
    clearTimeout(timeout);
  }

  return NextResponse.json({ web, api });
}
