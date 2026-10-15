import "server-only";

import { NextRequest, NextResponse } from "next/server";

import { API_INTERNAL_URL, collectorAuthHeaders, crossSiteRejection, signInRequired } from "@/lib/collectorApi";

const BACKEND_TIMEOUT_MS = 30_000;
const SEGMENT = /^[A-Za-z0-9._-]+$/;

/** Maps /api/me/** to the API path it may reach, or null (404).
 *
 * - /api/me and /api/me/<rest> → /me and /me/<rest> (the v1 accounts API)
 *
 * This is not a general proxy: every segment is a plain path token (no
 * "..", no encoded slashes), and everything lands under /me. The legacy
 * /api/me/legacy/<rest> branch went with the pre-v1 collection and wishlist
 * pages in Collector v1 S8: it answers 404 without reaching the API. */
export function upstreamPath(segments: readonly string[] | undefined): string | null {
  const parts = segments ?? [];
  if (parts.some((part) => !SEGMENT.test(part) || part === "." || part === "..")) return null;
  if (parts[0] === "legacy") return null;
  return parts.length ? `/me/${parts.join("/")}` : "/me";
}

const PASSED_RESPONSE_HEADERS = ["content-type", "content-disposition"];

/** One collector request: CSRF check, collector session check, mint a
 * 5-minute token, call the API server-to-server, pass the answer back
 * without the token. */
export async function proxyMe(request: NextRequest, segments: readonly string[] | undefined): Promise<Response> {
  const path = upstreamPath(segments);
  if (!path) return NextResponse.json({ error: "Not found" }, { status: 404 });

  const rejected = crossSiteRejection(request);
  if (rejected) return rejected;

  const auth = await collectorAuthHeaders();
  if (!auth) return signInRequired();

  const method = request.method.toUpperCase();
  const body = method === "POST" || method === "PUT" || method === "PATCH" ? await request.text() : undefined;
  const backendUrl = `${API_INTERNAL_URL}${path}${request.nextUrl.search}`;

  let backend: Response;
  try {
    backend = await fetch(backendUrl, {
      method,
      headers: { ...auth, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body || undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
  } catch (err) {
    const timedOut = err instanceof DOMException && (err.name === "TimeoutError" || err.name === "AbortError");
    console.error(`[me proxy] ${method} ${path} failed: ${timedOut ? "timed out" : "unreachable"}`);
    return NextResponse.json(
      { error: timedOut ? "Timed out waiting for backend API" : "Failed to reach backend API" },
      { status: 502 },
    );
  }

  const headers = new Headers({ "Cache-Control": "private, no-store" });
  for (const name of PASSED_RESPONSE_HEADERS) {
    const value = backend.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (backend.status === 204 || backend.status === 304) {
    return new Response(null, { status: backend.status, headers });
  }
  return new Response(backend.body, { status: backend.status, headers });
}
