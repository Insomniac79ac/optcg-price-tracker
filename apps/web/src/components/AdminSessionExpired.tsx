"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/** Shown in place of a failed admin data fetch (an AdminAuthRequiredError -
 * see lib/api.ts) once the admin session backing it has expired or was
 * revoked mid-page - there is no browser-held token to re-enter anymore
 * (see the removal of AdminAuthGate/localStorage admin_token), so the only
 * correct action is a fresh /admin/login, not a token form. */
export function AdminSessionExpired() {
  const pathname = usePathname();
  return (
    <div className="rounded-panel border border-signal-warning/40 bg-signal-warning/10 p-8 text-center">
      <p className="mb-3 text-sm text-signal-warning">
        Your admin session has expired or is no longer valid.
      </p>
      <Link
        href={`/admin/login?callbackUrl=${encodeURIComponent(pathname || "/admin")}`}
        className="rounded-control bg-accent-gold px-3 py-1.5 text-xs font-medium text-black/80 hover:bg-accent-gold-hover"
      >
        Sign in again
      </Link>
    </div>
  );
}
