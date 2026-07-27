import "server-only";

import { NextRequest, NextResponse } from "next/server";

import { getAdminIdentityForRouteHandler } from "@/lib/adminSession";

/** Shared server-side boundary + upstream-fetch helper for every
 * /api/admin/** Route Handler (and any other Next.js route that performs
 * admin work against the backend's X-Admin-Token-gated routes - see
 * src/app/api/file-jobs/route.ts). Two responsibilities, always paired:
 *
 * 1. Authorization: requireAdminOrResponse() calls
 *    getAdminIdentityForRouteHandler() (src/lib/adminSession.ts), which
 *    itself calls Auth.js auth() server-side - never trusts a role, email,
 *    or token read from the incoming request. A caller-supplied
 *    X-Admin-Token header is always ignored; only a validated role="admin"
 *    session grants access.
 * 2. Upstream auth: adminAuthHeaders() reads ADMIN_TOKEN from
 *    process.env - server-only, never NEXT_PUBLIC_*, never echoed back to
 *    the caller - and is the ONLY place a request to the backend's
 *    /admin/* routes gets its X-Admin-Token from. The browser never
 *    supplies or sees this value.
 *
 * proxyAdminJson() below composes both for the common case (JSON in,
 * JSON - or an empty/non-JSON passthrough - out). Routes that stream a
 * binary/CSV export or forward a multipart file upload can't reuse the body
 * handling (see cards/export, cards/import, backup/export, backup/restore)
 * but must still call requireAdminOrResponse() + adminAuthHeaders() for the
 * two responsibilities above. */

const API_INTERNAL_URL = process.env.API_INTERNAL_URL || "http://api:8000";
const DEFAULT_BACKEND_TIMEOUT_MS = 15_000;

/** Reads ADMIN_TOKEN server-side only. Never log, return, or forward this
 * value anywhere except as this one header on a server-to-server request to
 * API_INTERNAL_URL. */
export function adminAuthHeaders(): Record<string, string> {
  const token = process.env.ADMIN_TOKEN;
  return token ? { "X-Admin-Token": token } : {};
}

/** The Route Handler-side counterpart to requireAdminSession() (which is
 * for Server Components/Actions and redirects/404s instead of returning a
 * Response). Returns the validated identity, or a ready-to-return 401 JSON
 * response if the caller doesn't have an admin session - callers should
 * `return` that response immediately without contacting the backend. */
export async function requireAdminOrResponse(): Promise<
  { identity: { id: string; email: string } } | { response: NextResponse }
> {
  const identity = await getAdminIdentityForRouteHandler();
  if (!identity) {
    return {
      response: NextResponse.json({ error: "Admin session required." }, { status: 401 }),
    };
  }
  return { identity };
}

interface ProxyAdminJsonOptions {
  /** Overrides DEFAULT_BACKEND_TIMEOUT_MS for slower operations (imports,
   * merges, exports). */
  timeoutMs?: number;
  /** Short tag used in error log lines, e.g. "cache-status". Defaults to
   * backendPath. */
  logLabel?: string;
  /** Sent instead of an empty string when the caller's request body is
   * empty (e.g. "{}") - for routes whose backend Pydantic model rejects a
   * truly empty body on a bodyless POST. */
  emptyBodyFallback?: string;
}

/** The standard JSON-in/JSON-out admin proxy body, shared by the large
 * majority of /api/admin/** Route Handlers: authorize, forward the
 * caller's method/body to `${API_INTERNAL_URL}${backendPath}` with a
 * server-injected X-Admin-Token, and relay the backend's JSON response
 * (or a structured error if the backend was unreachable, timed out, or
 * returned a non-JSON/empty body). `backendPath` must include any query
 * string the caller wants forwarded (e.g. via `request.nextUrl.search`). */
export async function proxyAdminJson(
  request: NextRequest,
  backendPath: string,
  options?: ProxyAdminJsonOptions,
): Promise<NextResponse> {
  const auth = await requireAdminOrResponse();
  if ("response" in auth) return auth.response;

  const method = request.method.toUpperCase();
  const forwardsBody = method !== "GET" && method !== "HEAD";
  let body: string | undefined = forwardsBody ? await request.text() : undefined;
  if (forwardsBody && !body && options?.emptyBodyFallback) {
    body = options.emptyBodyFallback;
  }

  const headers: Record<string, string> = { ...adminAuthHeaders() };
  if (forwardsBody) headers["Content-Type"] = "application/json";

  const backendUrl = `${API_INTERNAL_URL}${backendPath}`;
  const timeoutMs = options?.timeoutMs ?? DEFAULT_BACKEND_TIMEOUT_MS;
  const label = options?.logLabel ?? backendPath;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  let backendResponse: Response;
  try {
    backendResponse = await fetch(backendUrl, {
      method,
      headers,
      body,
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (err) {
    const timedOut = err instanceof DOMException && err.name === "AbortError";
    console.error(
      `[${label} proxy] failed to reach backend at ${backendUrl}: ${
        timedOut ? `timed out after ${timeoutMs}ms` : String(err)
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
  const fallbackStatus = backendResponse.ok ? 502 : backendResponse.status;

  if (bodyText.length === 0) {
    return NextResponse.json(
      { error: "Empty response from backend API", backend_status: backendResponse.status },
      { status: fallbackStatus },
    );
  }

  try {
    const parsed = JSON.parse(bodyText);
    return NextResponse.json(parsed, { status: backendResponse.status });
  } catch {
    console.error(`[${label} proxy] backend response was not valid JSON (status=${backendResponse.status})`);
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
