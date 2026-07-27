import { requireAdminSession } from "@/lib/adminSession";

import { AdminSubNav } from "./AdminSubNav";

/**
 * Shared server-side boundary for every real /admin/* page - everything
 * except /admin/login, which lives outside this route group (Next.js route
 * groups don't affect the URL, only which layout wraps a page - see
 * app/admin/login/page.tsx) specifically so it can stay reachable without
 * an admin session while every page in here still requires one.
 *
 * Before this file existed, the only gate on any /admin/* page was each
 * page's own client-side <AdminAuthGate> - which only blocked the *data
 * fetch*, after the page shell, chrome, and full admin navigation had
 * already rendered. Then, for one task, this layout unconditionally 404'd
 * every request (no admin session concept existed yet). Now that
 * src/lib/auth.ts has a real Credentials-based admin session
 * (role="admin"), requireAdminSession() enforces it here: a signed-out
 * visitor is redirected to /admin/login (with callbackUrl preserved), and
 * a signed-in-but-not-admin visitor (e.g. an ordinary collector session)
 * gets a safe not-found rather than a page that reveals an /admin/* route
 * exists and is merely access-controlled - see src/lib/adminSession.ts.
 *
 * proxy.ts also does an *optimistic* redirect for signed-out /admin/*
 * requests (so a browser navigation doesn't even round-trip to this layout
 * first), but this layout is the real boundary - proxy.ts is explicitly
 * not allowed to be the only one (see proxy.ts's own comment on why).
 *
 * The backend's own X-Admin-Token check (services/api/app/auth.py) is
 * unchanged and remains the system of record for the admin API routes this
 * layout's pages call - this layout only stops the page shell itself from
 * rendering for a non-admin visitor, it is not a replacement for that
 * check (see src/lib/adminProxy.ts for the Route Handler side of this).
 */
export default async function ProtectedAdminLayout({ children }: { children: React.ReactNode }) {
  await requireAdminSession();
  return (
    <>
      <AdminSubNav />
      {children}
    </>
  );
}
