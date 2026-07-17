import fs from "node:fs";
import path from "node:path";

import { NextResponse } from "next/server";

// Server-side only - never exposed to the browser bundle (not NEXT_PUBLIC_*).
// Same reasoning as src/app/api/backend-health/route.ts.
const API_INTERNAL_URL = process.env.API_INTERNAL_URL || "http://api:8000";
const BACKEND_TIMEOUT_MS = 5_000;

/** apps/web's own Docker build context (./apps/web - see apps/web/Dockerfile)
 * doesn't include the repo-root VERSION file, so this only ever resolves
 * outside Docker (a local `next dev`/`next start` run from the repo
 * checkout). APP_VERSION (baked in as a build-time env var - see the
 * Makefile's prod-build target) is the real source of truth in a built
 * image; this is only the local-dev fallback. */
function readVersionFile(): string | null {
  const candidates = [
    path.join(/* turbopackIgnore: true */ process.cwd(), "VERSION"),
    path.join(/* turbopackIgnore: true */ process.cwd(), "..", "..", "VERSION"),
  ];
  for (const candidate of candidates) {
    try {
      const content = fs.readFileSync(candidate, "utf-8").trim();
      if (content) return content;
    } catch {
      continue;
    }
  }
  return null;
}

function getWebVersionInfo() {
  return {
    version: process.env.APP_VERSION || readVersionFile() || "0.0.0-unknown",
    git_commit: process.env.GIT_COMMIT || "unknown",
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
