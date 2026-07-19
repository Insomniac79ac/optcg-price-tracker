import { NextRequest, NextResponse } from "next/server";

import { auth } from "@/lib/auth";

const API_INTERNAL_URL = process.env.API_INTERNAL_URL || "http://api:8000";
const BACKEND_TIMEOUT_MS = 30_000;

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const headers: Record<string, string> = {};
  const session = await auth();
  if (session?.apiToken) headers["Authorization"] = `Bearer ${session.apiToken}`;
  const adminToken = request.headers.get("x-admin-token");
  if (adminToken) headers["X-Admin-Token"] = adminToken;

  const backendUrl = `${API_INTERNAL_URL}/file-jobs/${id}/download`;

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
      `[file-job-download proxy] failed to reach backend at ${backendUrl}: ${
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
          error: "Backend download failed",
          backend_status: backendResponse.status,
          body_preview: bodyText.slice(0, 500),
        },
        { status: backendResponse.status },
      );
    }
  }

  // Stream the file bytes straight through, preserving the backend's
  // Content-Type/Content-Disposition so the browser downloads it as a file
  // rather than rendering it inline - same approach as
  // /api/collection/export.
  const contentDisposition = backendResponse.headers.get("content-disposition");
  const responseHeaders: Record<string, string> = {
    "Content-Type": backendResponse.headers.get("content-type") || "application/octet-stream",
  };
  if (contentDisposition) responseHeaders["Content-Disposition"] = contentDisposition;

  return new NextResponse(backendResponse.body, {
    status: 200,
    headers: responseHeaders,
  });
}
