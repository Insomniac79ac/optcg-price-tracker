import Link from "next/link";
import { redirect } from "next/navigation";

import { AppHeader } from "@/components/AppHeader";
import { PageHeader } from "@/components/ui/PageHeader";
import { auth, isAdminLoginEnabled } from "@/lib/auth";
import { safeAdminCallbackUrl } from "@/lib/adminLoginUrl";

import { AdminLoginForm } from "./AdminLoginForm";


/** The public admin sign-in page - deliberately outside the
 * app/admin/(protected) route group so it stays reachable without a
 * session while every other /admin/* page requires role="admin" (see
 * (protected)/layout.tsx). Separate from /sign-in on purpose: that page is
 * the collector-only Google entry point and must not grow admin-login
 * functionality (see its own comment) - this is the temporary
 * Credentials-based admin login instead (src/lib/auth.ts,
 * services/api/app/api/admin_login.py). Staging/prototype only - see
 * docs/staging_deployment.md for the planned removal once Google OAuth
 * plus an admin-email allowlist replaces it. */
export default async function AdminLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string; reason?: string }>;
}) {
  const params = await searchParams;
  const safeDestination = safeAdminCallbackUrl(params.callbackUrl);

  // An already-signed-in admin visiting /admin/login again is sent straight
  // to their destination rather than shown the form a second time.
  const session = await auth();
  if (session?.user?.role === "admin" && !session.adminSessionExpired) {
    redirect(safeDestination);
  }

  const enabled = await isAdminLoginEnabled();

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-md px-4 py-10">
        <PageHeader
          title="Admin sign-in"
          description="Staging-only administrator access. Collector accounts use a separate sign-in."
        />

        <div className="panel space-y-4 p-6 text-sm text-text-secondary">
          {params.reason === "session-expired" && (
            <p role="status" className="rounded-control border border-accent-teal/40 bg-accent-teal/10 p-3 text-text-primary">
              Your administrator session expired. Sign in again to continue.
            </p>
          )}
          {enabled ? (
            <AdminLoginForm callbackUrl={safeDestination} />
          ) : (
            <p>Admin login is unavailable.</p>
          )}

          <div className="border-t border-border-muted pt-4 text-xs">
            <Link href="/" className="text-sky-400 hover:underline">
              ← Back to Discover
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
