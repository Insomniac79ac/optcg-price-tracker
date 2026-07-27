import { NextRequest, NextResponse } from "next/server";

import { adminAuthHeaders, requireAdminOrResponse } from "@/lib/adminProxy";

// Server-side only - never exposed to the browser bundle (not NEXT_PUBLIC_*).
// Defaults to the docker-compose service DNS name so this route works from
// inside the web container without needing the host-forwarded port that
// browser-side fetches struggle with in Codespaces/forwarded-port setups.
const API_INTERNAL_URL = process.env.API_INTERNAL_URL || "http://api:8000";
const BACKEND_TIMEOUT_MS = 60_000;

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ type: string }> },
) {
  const { type } = await params;
  const auth = await requireAdminOrResponse();
  if ("response" in auth) return auth.response;
  const headers: Record<string, string> = { ...adminAuthHeaders() };

  // Re-parse the incoming multipart body as FormData and hand it straight to
  // fetch as the outgoing body - fetch sets the correct
  // multipart/form-data Content-Type + boundary itself, so the file upload
  // is forwarded byte-for-byte without us re-encoding it.
  let formData: FormData;
  try {
    formData = await request.formData();
  } catch (err) {
    return NextResponse.json(
      { error: `Failed to read uploaded file: ${err instanceof Error ? err.message : String(err)}` },
      { status: 400 },
    );
  }

  const backendUrl = `${API_INTERNAL_URL}/admin/import-validation/${type}${request.nextUrl.search}`;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);

  let backendResponse: Response;
  try {
    backendResponse = await fetch(backendUrl, {
      method: "POST",
      headers,
      body: formData,
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (err) {
    const timedOut = err instanceof DOMException && err.name === "AbortError";
    console.error(
      `[import-validation proxy] failed to reach backend at ${backendUrl}: ${
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
      `[import-validation proxy] backend response was not valid JSON (status=${backendResponse.status})`,
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
