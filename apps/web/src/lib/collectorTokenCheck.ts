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
