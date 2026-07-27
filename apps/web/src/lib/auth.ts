import type { Account, Profile, Session, User } from "next-auth";
import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";
import type { JWT } from "next-auth/jwt";
import { SignJWT } from "jose";

const API_JWT_TTL = "1h";

// Temporary staging-only admin login (collector-blueprint.pdf, admin-login
// task) - a Credentials provider alongside the existing Google provider,
// verified server-side against the backend's POST /auth/admin/verify (see
// services/api/app/api/admin_login.py). This is a prototype meant to be
// removed once Google OAuth plus an admin-email allowlist replaces it - see
// docs/staging_deployment.md for the full architecture and removal plan.
//
// The callback/authorize bodies below are extracted into named exported
// functions (rather than inlined in the NextAuth() config, as the
// jwt/session callbacks used to be) purely so they're unit-testable without
// standing up a full NextAuth request/response cycle - see auth.test.ts.
export const ADMIN_CREDENTIALS_PROVIDER_ID = "admin-credentials";
const ADMIN_LOGIN_MAX_INPUT_LENGTH = 1024;

function apiJwtSecretKey(): Uint8Array {
  const secret = process.env.API_JWT_SECRET;
  if (!secret) {
    throw new Error("API_JWT_SECRET is not configured");
  }
  return new TextEncoder().encode(secret);
}

// Server-side only - never exposed to the browser bundle (not NEXT_PUBLIC_*).
// Same convention/fallback as every /api/admin/** route handler (see
// src/lib/adminProxy.ts).
function apiInternalUrl(): string {
  return process.env.API_INTERNAL_URL || "http://api:8000";
}

export function isNonEmptyBoundedString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= ADMIN_LOGIN_MAX_INPUT_LENGTH;
}

export interface AdminVerifyResponse {
  id: string;
  email: string;
  role: "admin";
}

/** Calls the backend's admin-credential verification endpoint - the only
 * caller of POST /auth/admin/verify; the browser never calls it directly
 * (see app.api.admin_login's module docstring on the backend side for why
 * that endpoint is deliberately outside require_admin_token). Returns null
 * on any failure - wrong credentials, throttled, disabled, or a network/
 * backend error - so adminAuthorize() below can't distinguish "wrong
 * password" from "backend unreachable" and accidentally leak that
 * distinction to the signed-out visitor. */
export async function verifyAdminCredentials(
  email: string,
  password: string,
): Promise<AdminVerifyResponse | null> {
  try {
    const response = await fetch(`${apiInternalUrl()}/auth/admin/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) return null;

    const data = (await response.json()) as Partial<AdminVerifyResponse>;
    if (data.role !== "admin" || !data.id || !data.email) return null;
    return { id: data.id, email: data.email, role: "admin" };
  } catch {
    return null;
  }
}

/** Backs /admin/login's proactive "admin login is not available" state
 * (see app/admin/login/page.tsx) - calls the same backend that
 * verifyAdminCredentials does, GET /auth/admin/status, which is
 * unauthenticated by design (there is no admin identity yet to gate it
 * behind) and reveals nothing beyond this one boolean. Fails closed
 * (treats a network/backend error as "not enabled") rather than showing a
 * login form that would only fail once submitted. */
export async function isAdminLoginEnabled(): Promise<boolean> {
  try {
    const response = await fetch(`${apiInternalUrl()}/auth/admin/status`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5_000),
    });
    if (!response.ok) return false;
    const data = (await response.json()) as { enabled?: unknown };
    return data.enabled === true;
  } catch {
    return false;
  }
}

/** The admin Credentials provider's authorize() - separated out so it's
 * unit-testable directly (see auth.test.ts) without going through
 * NextAuth's own request handling. */
export async function adminAuthorize(
  credentials: Partial<Record<"email" | "password", unknown>> | undefined,
): Promise<{ id: string; email: string; role: "admin" } | null> {
  const email = credentials?.email;
  const password = credentials?.password;
  if (!isNonEmptyBoundedString(email) || !isNonEmptyBoundedString(password)) {
    return null;
  }
  const verified = await verifyAdminCredentials(email, password);
  if (!verified) return null;
  return { id: verified.id, email: verified.email, role: "admin" };
}

// A genuinely short admin session, independent of whatever session.maxAge
// ends up being appropriate for collector Google sign-in once that's live
// (Google OAuth has no credentials configured yet - see docs/
// staging_deployment.md - so there is no current collector session for a
// shorter global maxAge to prematurely affect; this will need revisiting,
// not necessarily widening, once that changes). Enforced as a claim inside
// the JWT itself (roleExpiresAt) rather than session.maxAge, so it stays
// admin-specific even after Google sign-in is enabled.
export const ADMIN_SESSION_MAX_AGE_MS = 4 * 60 * 60 * 1000;

interface JwtCallbackParams {
  token: JWT;
  profile?: Profile;
  user?: User;
  account?: Account | null;
}

/** The jwt callback body - see ADMIN_SESSION_MAX_AGE_MS above and
 * auth.test.ts for what this must and must not put on the token (a role
 * claim, an expiry for it; never a password, hash, or ADMIN_TOKEN). */
export function applyJwtCallback({ token, profile, user, account }: JwtCallbackParams): JWT {
  // `profile` is only present on the initial sign-in request - carry the
  // Google account's stable id/email/name/picture forward into every
  // subsequent token refresh.
  if (profile) {
    token.sub = profile.sub as string;
    token.email = profile.email as string;
    token.name = profile.name as string | undefined;
    token.picture = profile.picture as string | undefined;
    token.role = undefined;
    token.roleExpiresAt = undefined;
    return token;
  }

  // `user`/`account` are likewise only present on the initial sign-in
  // request - adminAuthorize()'s return value becomes `user` here.
  if (account?.provider === ADMIN_CREDENTIALS_PROVIDER_ID && user) {
    token.sub = user.id;
    token.email = user.email as string;
    token.role = "admin";
    token.roleExpiresAt = Date.now() + ADMIN_SESSION_MAX_AGE_MS;
    return token;
  }

  // Every subsequent request for an existing admin token: enforce the
  // short admin-specific lifetime by demoting the role claim once it
  // expires, without touching the underlying Auth.js session cookie (see
  // ADMIN_SESSION_MAX_AGE_MS above).
  const roleExpiresAt = token.roleExpiresAt as number | undefined;
  if (token.role === "admin" && (!roleExpiresAt || Date.now() > roleExpiresAt)) {
    token.role = undefined;
    token.roleExpiresAt = undefined;
  }

  return token;
}

/** The session callback body - see auth.test.ts for what this must and
 * must not expose (role, never API_JWT_SECRET/ADMIN_TOKEN/a password hash;
 * never mints the collector apiToken for an admin session - see the
 * comment inline below for why). */
export async function applySessionCallback({
  session,
  token,
}: {
  session: Session;
  token: JWT;
}): Promise<Session> {
  if (session.user) {
    session.user.id = token.sub as string;
    session.user.role = token.role === "admin" ? "admin" : undefined;
  }

  if (token.role === "admin") {
    // Admin sessions authenticate to the backend via a server-side-
    // injected ADMIN_TOKEN (see src/lib/adminProxy.ts), never this
    // per-user bearer JWT - minting one here would needlessly JIT-
    // provision a phantom `users` row for the fixed "staging-admin"
    // subject the moment anything ever presented it to
    // require_current_user (see services/api/app/auth.py).
    return session;
  }

  // Mints a short-lived, separately-signed bearer token for the FastAPI
  // backend (which lives on a different host/domain and can't easily
  // verify NextAuth's own encrypted session JWE) - see docs/deployment.md
  // for the full rationale. Session-only; never persisted anywhere besides
  // the client's in-memory session object.
  const apiToken = await new SignJWT({
    email: token.email as string,
    name: token.name as string | undefined,
  })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(token.sub as string)
    .setIssuedAt()
    .setExpirationTime(API_JWT_TTL)
    .sign(apiJwtSecretKey());

  session.apiToken = apiToken;
  return session;
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Google,
    Credentials({
      id: ADMIN_CREDENTIALS_PROVIDER_ID,
      name: "Admin",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      authorize: adminAuthorize,
    }),
  ],
  session: { strategy: "jwt" },
  // Vercel sets the incoming request's Host header safely (it can't be
  // spoofed by the client - Vercel's edge network overwrites it), so
  // trusting it here is the documented-safe case, not a host-header-
  // injection risk. Without this, proxy.ts's `auth()` wrapper throws
  // UntrustedHost internally (see https://errors.authjs.dev#untrustedhost)
  // and - critically - fails *open*: the protected route it's wrapping
  // renders normally instead of redirecting to /sign-in. Reproduced
  // locally via `next start` (which lacks Vercel's auto-detection) while
  // investigating why proxy.ts wasn't gating /collection etc. in staging.
  trustHost: true,
  callbacks: {
    jwt: applyJwtCallback,
    session: applySessionCallback,
  },
});
