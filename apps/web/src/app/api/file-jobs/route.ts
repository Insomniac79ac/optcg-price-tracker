import { NextRequest, NextResponse } from "next/server";

import { auth } from "@/lib/auth";

// Server-side only - never exposed to the browser bundle (not NEXT_PUBLIC_*).
// Defaults to the docker-compose service DNS name so this route works from
// inside the web container without needing the host-forwarded port that
// browser-side fetches struggle with in Codespaces/forwarded-port setups.
const API_INTERNAL_URL = process.env.API_INTERNAL_URL || "http://api:8000";
const BACKEND_TIMEOUT_MS = 15_000;

// GET /file-jobs accepts EITHER a signed-in user's session (forwarded as a
// bearer token, same as /api/collection/export) OR an X-Admin-Token header
// (forwarded as-is, same as /api/admin/cache/status) - see
// app.auth.file_job_access on the backend. Both are attached here whenever
// present so this one route works for the collection/wishlist background
// import/export UI (session only) and the /admin/file-jobs page (admin
// token only, typically no session) alike.
async function buildHeaders(request: NextRequest): Promise<Record<string, string>> {
  const headers: Record<string, string> = {};
  const session = await auth();
  if (session?.apiToken) headers["Authorization"] = `Bearer ${session.apiToken}`;
  const adminToken = request.headers.get("x-admin-token");
  if (adminToken) headers["X-Admin-Token"] = adminToken;
  return headers;
}

export async function GET(request: NextRequest) {
  const headers = await buildHeaders(request);
  const backendUrl = `${API_INTERNAL_URL}/file-jobs${request.nextUrl.search}`;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);

  let backendResponse: Response;
  try {
    backendResponse = await fetch(backendUrl, {
      headers,
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (err) {
    const timedOut = err instanceof DOMException && err.name === "AbortError";
    console.error(
      `[file-jobs proxy] failed to reach backend at ${backendUrl}: ${
        timedOut ? `timed out after ${BACKEND_TIMEOUT_MS}ms` : String(err)
      }`,
    );
    return NextResponse.json(
      {
        error: timedOut
          ? "Timed out waiting for backend API"
          : "Failed to reach backend API",
      },
      { status: 502 },
    );
  } finally {
    clearTimeout(timeout);
  }

  const bodyText = await backendResponse.text();
  const fallbackStatus = backendResponse.ok ? 502 : backendResponse.status;

  if (bodyText.length === 0) {
    return NextResponse.json(
      {
        error: "Empty response from backend API",
        backend_status: backendResponse.status,
      },
      { status: fallbackStatus },
    );
  }

  try {
    const parsed = JSON.parse(bodyText);
    return NextResponse.json(parsed, { status: backendResponse.status });
  } catch {
    console.error(
      `[file-jobs proxy] backend response was not valid JSON (status=${backendResponse.status})`,
    );
    return NextResponse.json(
      {
        error: "Invalid JSON from backend API",
        backend_status: backendResponse.status,
        body_preview: bodyText.slice(0, 500),
      },
      { status: fallbackStatus },
    );
  }
}
