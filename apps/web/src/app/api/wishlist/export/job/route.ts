import { NextRequest, NextResponse } from "next/server";

import { auth } from "@/lib/auth";

// Server-side only - never exposed to the browser bundle (not NEXT_PUBLIC_*).
const API_INTERNAL_URL = process.env.API_INTERNAL_URL || "http://api:8000";
const BACKEND_TIMEOUT_MS = 15_000;

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session?.apiToken) {
    return NextResponse.json({ error: "Sign-in required" }, { status: 401 });
  }
  const headers: Record<string, string> = {
    Authorization: `Bearer ${session.apiToken}`,
    "Content-Type": "application/json",
  };

  const body = await request.text();
  const backendUrl = `${API_INTERNAL_URL}/wishlist/export.csv/job`;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);

  let backendResponse: Response;
  try {
    backendResponse = await fetch(backendUrl, {
      method: "POST",
      headers,
      body: body || "{}",
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (err) {
    const timedOut = err instanceof DOMException && err.name === "AbortError";
    console.error(
      `[wishlist-export-job proxy] failed to reach backend at ${backendUrl}: ${
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
      `[wishlist-export-job proxy] backend response was not valid JSON (status=${backendResponse.status})`,
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
