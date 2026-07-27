import { NextRequest, NextResponse } from "next/server";

import { adminAuthHeaders } from "@/lib/adminProxy";
import { auth } from "@/lib/auth";

const API_INTERNAL_URL = process.env.API_INTERNAL_URL || "http://api:8000";
const BACKEND_TIMEOUT_MS = 15_000;

// Accepts EITHER a signed-in collector session (bearer token) OR a
// role="admin" Auth.js session (server-side-injected X-Admin-Token) - see
// src/app/api/file-jobs/route.ts for the full rationale.
async function buildHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = {};
  const session = await auth();
  if (session?.apiToken) headers["Authorization"] = `Bearer ${session.apiToken}`;
  if (session?.user?.role === "admin") Object.assign(headers, adminAuthHeaders());
  return headers;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const headers = await buildHeaders();
  const backendUrl = `${API_INTERNAL_URL}/file-jobs/${id}`;

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
      `[file-job proxy] failed to reach backend at ${backendUrl}: ${
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
      `[file-job proxy] backend response was not valid JSON (status=${backendResponse.status})`,
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
