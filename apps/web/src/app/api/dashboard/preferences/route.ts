import { NextRequest, NextResponse } from "next/server";

import { auth } from "@/lib/auth";

// Server-side only - never exposed to the browser bundle (not NEXT_PUBLIC_*).
// Defaults to the docker-compose service DNS name so this route works from
// inside the web container without needing the host-forwarded port that
// browser-side fetches struggle with in Codespaces/forwarded-port setups.
const API_INTERNAL_URL = process.env.API_INTERNAL_URL || "http://api:8000";
const BACKEND_TIMEOUT_MS = 15_000;

async function proxy(
  method: "GET" | "PATCH",
  request: NextRequest,
): Promise<NextResponse> {
  const session = await auth();
  if (!session?.apiToken) {
    return NextResponse.json({ error: "Sign-in required" }, { status: 401 });
  }

  let body: string | undefined;
  if (method === "PATCH") {
    body = await request.text();
  }

  const backendUrl = `${API_INTERNAL_URL}/dashboard/preferences`;
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
      `[dashboard-preferences proxy] failed to reach backend at ${backendUrl}: ${
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
      `[dashboard-preferences proxy] backend response was not valid JSON (status=${backendResponse.status})`,
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

export async function GET(request: NextRequest) {
  return proxy("GET", request);
}

export async function PATCH(request: NextRequest) {
  return proxy("PATCH", request);
}
