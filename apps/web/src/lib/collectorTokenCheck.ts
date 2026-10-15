import "server-only";

import { API_INTERNAL_URL, mintProbeToken } from "@/lib/collectorApi";

/** Does the API accept a pass this website signs? (2026-10-15: the two
 * copies of API_JWT_SECRET had diverged between Vercel and Railway, every
 * collector request got 401, and /account showed only "could not be
 * loaded".)
 *
 * The probe pass is signed exactly like a collector's but carries no email,
 * so the API refuses it *after* checking the signature and *before* creating
 * a user (services/api/app/auth.py). Its answer tells the two cases apart:
 *   "Token missing required claims" → signature accepted: secrets match
 *   "Invalid or expired token"      → signature refused: secrets differ
 * The pass grants nothing anywhere and is never returned to the caller. */
export type TokenCheckStatus = "ok" | "mismatch" | "disabled" | "unconfigured" | "unexpected" | "unreachable";

const TIMEOUT_MS = 10_000;

export async function checkCollectorToken(): Promise<TokenCheckStatus> {
  if (!process.env.API_JWT_SECRET) return "unconfigured";
  let response: Response;
  try {
    response = await fetch(`${API_INTERNAL_URL}/me/profile`, {
      headers: { Authorization: `Bearer ${await mintProbeToken()}` },
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    return "unreachable";
  }
  // COLLECTOR_ACCOUNTS_ENABLED off: /me is 404 before any token check.
  if (response.status === 404) return "disabled";
  const detail = await response.json().then((body: { detail?: unknown }) => body?.detail, () => undefined);
  if (response.status === 401 && detail === "Token missing required claims") return "ok";
  if (response.status === 401 && detail === "Invalid or expired token") return "mismatch";
  return "unexpected";
}

/** How long one answer is reused. The route is public, so without this every
 * request made the website call the API, and the API counts all website
 * traffic against one shared public-read bucket. */
export const TOKEN_CHECK_CACHE_MS = 60_000;

let cached: { status: TokenCheckStatus; expiresAt: number } | null = null;
let inflight: Promise<TokenCheckStatus> | null = null;

/** checkCollectorToken, at most once per TOKEN_CHECK_CACHE_MS per server
 * instance; concurrent callers share one API call. */
export function cachedCollectorTokenCheck(): Promise<TokenCheckStatus> {
  if (cached && cached.expiresAt > Date.now()) return Promise.resolve(cached.status);
  if (!inflight) {
    inflight = checkCollectorToken()
      .then((status) => {
        cached = { status, expiresAt: Date.now() + TOKEN_CHECK_CACHE_MS };
        if (status !== "ok") console.error(`[collector token check] ${status}`);
        return status;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/** Requests per client per window; scripts/verify_staging_delivery.py sends
 * one per delivery and honours Retry-After on 429. */
export const TOKEN_CHECK_LIMIT = 10;
export const TOKEN_CHECK_WINDOW_MS = 60_000;
const MAX_TRACKED_CLIENTS = 10_000;

const windows = new Map<string, { windowStart: number; count: number }>();

/** Fixed-window count per client IP, in this server instance's memory.
 * Returns seconds until the window resets when over the limit, else null. */
export function tokenCheckRetryAfter(clientKey: string, now = Date.now()): number | null {
  const windowStart = now - (now % TOKEN_CHECK_WINDOW_MS);
  let entry = windows.get(clientKey);
  if (!entry || entry.windowStart !== windowStart) {
    if (windows.size >= MAX_TRACKED_CLIENTS) windows.clear();
    entry = { windowStart, count: 0 };
    windows.set(clientKey, entry);
  }
  entry.count += 1;
  if (entry.count <= TOKEN_CHECK_LIMIT) return null;
  return Math.max(1, Math.ceil((windowStart + TOKEN_CHECK_WINDOW_MS - now) / 1000));
}

/** The client address Vercel reports (it overwrites X-Forwarded-For). */
export function tokenCheckClientKey(headers: Headers): string {
  const forwarded = headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  return forwarded || headers.get("x-real-ip")?.trim() || "unknown";
}

/** Test-only: forget the cached answer and every client's count. */
export function resetTokenCheckState(): void {
  cached = null;
  inflight = null;
  windows.clear();
}
