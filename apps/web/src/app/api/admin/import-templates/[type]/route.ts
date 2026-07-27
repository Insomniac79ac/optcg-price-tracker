import { NextRequest, NextResponse } from "next/server";

import { adminAuthHeaders, requireAdminOrResponse } from "@/lib/adminProxy";

// Server-side only - never exposed to the browser bundle (not NEXT_PUBLIC_*).
// Defaults to the docker-compose service DNS name so this route works from
// inside the web container without needing the host-forwarded port that
// browser-side fetches struggle with in Codespaces/forwarded-port setups.
const API_INTERNAL_URL = process.env.API_INTERNAL_URL || "http://api:8000";
const BACKEND_TIMEOUT_MS = 15_000;

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ type: string }> },
) {
  const { type } = await params;
  const auth = await requireAdminOrResponse();
  if ("response" in auth) return auth.response;
  const headers: Record<string, string> = { ...adminAuthHeaders() };

  const backendUrl = `${API_INTERNAL_URL}/admin/import-templates/${type}.csv`;

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
      `[import-template-download proxy] failed to reach backend at ${backendUrl}: ${
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

  if (!backendResponse.ok) {
    const bodyText = await backendResponse.text();
    try {
      const parsed = JSON.parse(bodyText);
      return NextResponse.json(parsed, { status: backendResponse.status });
    } catch {
      return NextResponse.json(
        {
          error: "Backend template download failed",
          backend_status: backendResponse.status,
          body_preview: bodyText.slice(0, 500),
        },
        { status: backendResponse.status },
      );
    }
  }

  // Stream the CSV bytes straight through, preserving the backend's
  // Content-Type/Content-Disposition so the browser downloads it as a file
  // rather than rendering it inline.
  const contentDisposition = backendResponse.headers.get("content-disposition");
  const responseHeaders: Record<string, string> = {
    "Content-Type": backendResponse.headers.get("content-type") || "text/csv",
  };
  if (contentDisposition) responseHeaders["Content-Disposition"] = contentDisposition;

  return new NextResponse(backendResponse.body, {
    status: 200,
    headers: responseHeaders,
  });
}
