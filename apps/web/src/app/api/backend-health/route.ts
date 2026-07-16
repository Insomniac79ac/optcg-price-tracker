import { NextResponse } from "next/server";

// Server-side only - never exposed to the browser bundle (not NEXT_PUBLIC_*).
// Defaults to the docker-compose service DNS name so this route works from
// inside the web container without needing the host-forwarded port that
// browser-side fetches struggle with in Codespaces/forwarded-port setups.
const API_INTERNAL_URL = process.env.API_INTERNAL_URL || "http://api:8000";
const BACKEND_TIMEOUT_MS = 5_000;

// Unauthenticated, like the api's own GET /health - lets an operator (or an
// uptime monitor) check "is the backend actually reachable and healthy"
// through the web app's own public domain, without needing api exposed on
// its own public port. See "Production deployment behind HTTPS reverse
// proxy" in docs/deployment.md.
export async function GET() {
  const backendUrl = `${API_INTERNAL_URL}/health`;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);

  let backendResponse: Response;
  try {
    backendResponse = await fetch(backendUrl, {
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (err) {
    const timedOut = err instanceof DOMException && err.name === "AbortError";
    console.error(
      `[backend-health proxy] failed to reach backend at ${backendUrl}: ${
        timedOut ? `timed out after ${BACKEND_TIMEOUT_MS}ms` : String(err)
      }`,
    );
    return NextResponse.json(
      {
        status: "error",
        service: "web",
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
  if (bodyText.length === 0) {
    return NextResponse.json(
      {
        status: "error",
        service: "web",
        error: "Empty response from backend API",
        backend_status: backendResponse.status,
      },
      { status: 502 },
    );
  }

  let backendBody: unknown;
  try {
    backendBody = JSON.parse(bodyText);
  } catch {
    console.error(
      `[backend-health proxy] backend response was not valid JSON (status=${backendResponse.status})`,
    );
    return NextResponse.json(
      {
        status: "error",
        service: "web",
        error: "Invalid JSON from backend API",
        backend_status: backendResponse.status,
        body_preview: bodyText.slice(0, 500),
      },
      { status: 502 },
    );
  }

  return NextResponse.json(
    { service: "web", backend: backendBody },
    { status: backendResponse.status },
  );
}
