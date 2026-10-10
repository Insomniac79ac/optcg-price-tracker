import { requireAdminSession } from "@/lib/adminSession";

/** Server-side boundary for the internal market-intelligence pages outside
 * /admin (/market/signals, /market/signal-events, /market/opportunities,
 * /market/report). Their data is admin-only - the backend routes require
 * X-Admin-Token and the Route Handlers require an admin session - because it
 * is market-wide and carries ownership and portfolio figures summed across
 * every collection. requireAdminSession() gives a collector session a
 * not-found and a signed-out visitor the admin login, exactly as the
 * app/admin/(protected) layout does. */
export async function AdminOnlyPageLayout({ children }: { children: React.ReactNode }) {
  await requireAdminSession();
  return children;
}
