import { notFound } from "next/navigation";

/**
 * Shared server-side boundary for the entire /admin/* route group.
 *
 * Before this file existed, the only gate on any /admin/* page was each
 * page's own client-side <AdminAuthGate> - which only blocked the *data
 * fetch*, after the page shell, chrome, and full admin navigation had
 * already rendered (see collector-blueprint.pdf Part 7/9). This layout
 * wraps every /admin/* page and route segment, so it runs first, server
 * side, before any of that ever reaches the browser.
 *
 * There is currently no admin session concept at all - no `role` field on
 * the User model, no `role` in the Auth.js session/JWT (see
 * src/lib/auth.ts). That is deliberate: this task migrates the frontend
 * containment only. The dedicated admin-login task (collector-
 * blueprint.pdf Phase 10 - a Credentials provider alongside the existing
 * Google provider) is what will give this layout something real to check.
 *
 * Until then, per that same task's explicit instruction to prefer a 404
 * over pretending a login exists, every request here - signed out,
 * signed-in collector, or anyone else - gets a 404. Do not replace this
 * with a fake/always-true role check; wire in a real
 * `session?.user?.role === "admin"` check (and the corresponding 403/redirect
 * behaviour for an authenticated-but-non-admin visitor) only once that
 * session field actually exists.
 *
 * The backend's own X-Admin-Token check (services/api/app/auth.py) is
 * unchanged and remains the system of record for the admin API routes this
 * layout's pages call - this layout only stops the page shell itself from
 * rendering, it is not a replacement for that check.
 */
export default function AdminLayout() {
  notFound();
}
