import "server-only";

import type { Session } from "next-auth";
import { NextResponse } from "next/server";
import { SignJWT } from "jose";

import { auth } from "@/lib/auth";

/** Server-side boundary for every per-user (collector) request to the API.
 *
 * Collector v1 S5 (PLAN §D1, owner decision Q2): the browser never holds a
 * bearer token. The Auth.js session object carries no `apiToken`; instead a
 * Next route handler checks the signed-in collector session and mints a
 * short-lived API JWT here, on the server, for one upstream request to
 * API_INTERNAL_URL. The token is never returned to the caller.
 *
 * Only a Google ("collector") session gets a token. An admin session
 * authenticates with the server-side ADMIN_TOKEN (src/lib/adminProxy.ts) and
 * must never present a user JWT: its fixed subject would JIT-provision a
 * phantom `users` row (services/api/app/auth.py). */

export const API_TOKEN_TTL_SECONDS = 5 * 60;

export const API_INTERNAL_URL = process.env.API_INTERNAL_URL || "http://api:8000";

export interface CollectorIdentity {
  sub: string;
  email: string;
  name?: string;
}

/** The collector identity behind a session, or null for anything else: no
 * session, an admin session (active or expired), or a session missing the
 * stable Google subject or email the API needs. */
export function collectorIdentity(session: Session | null | undefined): CollectorIdentity | null {
  if (!session || session.sessionKind !== "collector") return null;
  const sub = session.user?.id;
  const email = session.user?.email;
  if (typeof sub !== "string" || !sub || typeof email !== "string" || !email) return null;
  const name = typeof session.user?.name === "string" && session.user.name ? session.user.name : undefined;
  return { sub, email, name };
}

function apiJwtSecretKey(): Uint8Array {
  const secret = process.env.API_JWT_SECRET;
  if (!secret) {
    throw new Error("API_JWT_SECRET is not configured");
  }
  return new TextEncoder().encode(secret);
}

/** A 5-minute HS256 token for one server-to-server API request. */
export async function mintApiToken(identity: CollectorIdentity): Promise<string> {
  return new SignJWT({ email: identity.email, ...(identity.name ? { name: identity.name } : {}) })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(identity.sub)
    .setIssuedAt()
    .setExpirationTime(`${API_TOKEN_TTL_SECONDS}s`)
    .sign(apiJwtSecretKey());
}

/** The pass /api/collector-token-check sends (src/lib/collectorTokenCheck.ts):
 * signed like a collector's but with a fixed subject and no email, so the API
 * refuses it after the signature check and before creating a user. */
export async function mintProbeToken(): Promise<string> {
  return new SignJWT({})
    .setProtectedHeader({ alg: "HS256" })
    .setSubject("collector-token-check")
    .setIssuedAt()
    .setExpirationTime("60s")
    .sign(apiJwtSecretKey());
}

/** Authorization header for the signed-in collector, or null when the caller
 * is not a collector (callers answer 401 without contacting the API). */
export async function collectorAuthHeaders(): Promise<Record<string, string> | null> {
  return collectorAuthHeadersFor(await auth());
}

/** Same, for a handler that already holds the session (e.g. one that also
 * accepts an admin session for the same route). */
export async function collectorAuthHeadersFor(session: Session | null | undefined): Promise<Record<string, string> | null> {
  const identity = collectorIdentity(session);
  if (!identity) return null;
  return { Authorization: `Bearer ${await mintApiToken(identity)}` };
}

// Moved to src/lib/crossSite.ts so the admin proxies share it (audit F9).
export { crossSiteRejection } from "@/lib/crossSite";

export function signInRequired(): NextResponse {
  return NextResponse.json({ error: "Sign-in required" }, { status: 401, headers: { "Cache-Control": "private, no-store" } });
}
