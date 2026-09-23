import "server-only";

import { notFound, redirect } from "next/navigation";
import { headers } from "next/headers";

import { auth } from "@/lib/auth";
import { ADMIN_CALLBACK_HEADER, adminLoginHref } from "@/lib/adminLoginUrl";

/** The single server-side authorization boundary for "is this request an
 * authenticated admin" - used by app/admin/(protected)/layout.tsx, every
 * sensitive /api/admin/** Route Handler (via src/lib/adminProxy.ts, which
 * wraps getAdminIdentity below), and any admin Server Action. Always calls
 * Auth.js auth() itself; never trusts a role read from request headers,
 * query strings, or form fields - see src/lib/auth.ts's session callback
 * for the only place session.user.role is ever set. The `server-only`
 * import makes an accidental client-component import of this module a
 * build error, not just a lint nit. */

export interface AdminIdentity {
  id: string;
  email: string;
}

async function resolveAdminIdentity(): Promise<{
  signedIn: boolean;
  expiredAdmin: boolean;
  identity: AdminIdentity | null;
}> {
  const session = await auth();
  const expiredAdmin = session?.sessionKind === "admin" && session.adminSessionExpired === true;
  if (expiredAdmin || session?.user?.role !== "admin" || !session.user.email) {
    return { signedIn: Boolean(session), expiredAdmin, identity: null };
  }
  return {
    signedIn: true,
    expiredAdmin: false,
    identity: { id: session.user.id ?? "staging-admin", email: session.user.email },
  };
}

/** For Server Components (layouts, pages, Server Actions) - returns the
 * validated admin identity, or ends the request itself: a signed-out
 * visitor or expired administrator is redirected to /admin/login with a safe
 * callback. A signed-in-but-not-admin visitor
 * (e.g. a collector session) gets a safe not-found rather than a page that
 * reveals an /admin/* route exists and is merely access-controlled. Both
 * `redirect()` and `notFound()` throw internally - this function never
 * actually returns null, so callers don't need their own failure branch. */
export async function requireAdminSession(): Promise<AdminIdentity> {
  const { signedIn, expiredAdmin, identity } = await resolveAdminIdentity();
  if (identity) return identity;
  if (!signedIn || expiredAdmin) {
    // Proxy overwrites this navigation hint; it is sanitized again here and
    // never participates in the authorization decision above.
    const callback = (await headers()).get(ADMIN_CALLBACK_HEADER);
    redirect(adminLoginHref(callback, expiredAdmin));
  }
  notFound();
}

/** For Route Handlers, which must return a Response rather than throw a
 * page-style redirect (a caller expecting JSON should see 401/403 JSON,
 * not transparently follow a redirect to an HTML login page) - returns
 * null on any non-admin session, leaving the response shape to the caller.
 * See src/lib/adminProxy.ts, which every /api/admin/** handler goes
 * through rather than calling this directly. */
export async function getAdminIdentityForRouteHandler(): Promise<AdminIdentity | null> {
  const { identity } = await resolveAdminIdentity();
  return identity;
}
