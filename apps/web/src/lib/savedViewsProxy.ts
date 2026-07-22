import { NextRequest, NextResponse } from "next/server";

import { auth } from "@/lib/auth";

// Server-side only - never exposed to the browser bundle (not NEXT_PUBLIC_*).
// Defaults to the docker-compose service DNS name so this route works from
// inside the web container without needing the host-forwarded port that
// browser-side fetches struggle with in Codespaces/forwarded-port setups.
const API_INTERNAL_URL = process.env.API_INTERNAL_URL || "http://api:8000";
const BACKEND_TIMEOUT_MS = 15_000;

/** Shared proxy body for every /api/saved-views/** route - mirrors
 * src/app/api/dashboard/preferences/route.ts's auth/timeout/error-parsing
 * pattern, with one addition: a 204 (DELETE /saved-views/{id}, POST
 * /clear-default) is translated into a small JSON success body rather than
 * forwarded as an empty response, since fetchAdminJson (the frontend
 * caller, see src/lib/api.ts) always calls res.json() on success. */
export async function proxySavedViews(
  method: "GET" | "POST" | "PATCH" | "DELETE",
  request: NextRequest,
  backendPath: string,
): Promise<NextResponse> {
  const session = await auth();
  if (!session?.apiToken) {
    return NextResponse.json({ error: "Sign-in required" }, { status: 401 });
  }

  let body: string | undefined;
  if (method === "POST" || method === "PATCH") {
    body = await request.text();
  }

  const search = request.nextUrl.search;
  const backendUrl = `${API_INTERNAL_URL}${backendPath}${search}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);

  let backendResponse: Response;
  try {
    backendResponse = await fetch(backendUrl, {
      method,
      headers: {
        Authorization: `Bearer ${session.apiToken}`,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body,
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (err) {
    const timedOut = err instanceof DOMException && err.name === "AbortError";
    console.error(
      `[saved-views proxy] failed to reach backend at ${backendUrl}: ${
        timedOut ? `timed out after ${BACKEND_TIMEOUT_MS}ms` : String(err)
      }`,
    );
    return NextResponse.json(
      { error: timedOut ? "Timed out waiting for backend API" : "Failed to reach backend API" },
      { status: 502 },
    );
  } finally {
    clearTimeout(timeout);
  }

  if (backendResponse.status === 204) {
    return NextResponse.json({ success: true }, { status: 200 });
  }

  const bodyText = await backendResponse.text();

  if (bodyText.length === 0) {
    return NextResponse.json(
      { error: "Empty response from backend API", backend_status: backendResponse.status },
      { status: backendResponse.ok ? 502 : backendResponse.status },
    );
  }

  try {
    const parsed = JSON.parse(bodyText);
    return NextResponse.json(parsed, { status: backendResponse.status });
  } catch {
    console.error(
      `[saved-views proxy] backend response was not valid JSON (status=${backendResponse.status})`,
    );
    return NextResponse.json(
      {
        error: "Invalid JSON from backend API",
        backend_status: backendResponse.status,
        body_preview: bodyText.slice(0, 500),
      },
      { status: backendResponse.ok ? 502 : backendResponse.status },
    );
  }
}
