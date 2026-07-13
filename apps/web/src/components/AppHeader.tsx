"use client";

import Link from "next/link";
import { signIn, signOut, useSession } from "next-auth/react";

export function AppHeader() {
  return (
    <header className="sticky top-0 z-10 border-b border-neutral-800 bg-neutral-950/95 backdrop-blur">
      <div className="mx-auto flex h-12 max-w-7xl items-center gap-6 px-4">
        <Link
          href="/dashboard"
          className="text-sm font-semibold tracking-tight text-neutral-100"
        >
          OPTCG Price Tracker
        </Link>
        <nav className="flex flex-1 items-center gap-4 text-sm text-neutral-400">
          <Link href="/dashboard" className="hover:text-neutral-100">
            Dashboard
          </Link>
          <Link href="/collection" className="hover:text-neutral-100">
            Collection
          </Link>
          <Link href="/wishlist" className="hover:text-neutral-100">
            Wishlist
          </Link>
          <Link href="/grading" className="hover:text-neutral-100">
            Grading
          </Link>
          <Link href="/market/movers" className="hover:text-neutral-100">
            Market movers
          </Link>
          <Link href="/market/signals" className="hover:text-neutral-100">
            Market signals
          </Link>
          <Link href="/market/signal-events" className="hover:text-neutral-100">
            Signal events
          </Link>
          <Link href="/market/opportunities" className="hover:text-neutral-100">
            Opportunities
          </Link>
          <Link href="/market/report" className="hover:text-neutral-100">
            Report
          </Link>
          <Link
            href="/admin/refresh-runs"
            className="hover:text-neutral-100"
          >
            Refresh runs
          </Link>
          <Link
            href="/admin/market-workflow-runs"
            className="hover:text-neutral-100"
          >
            Workflow runs
          </Link>
          <Link
            href="/admin/snkrdunk-candidates"
            className="hover:text-neutral-100"
          >
            SNKRDUNK candidates
          </Link>
          <Link href="/admin/alerts" className="hover:text-neutral-100">
            Alerts
          </Link>
          <Link href="/admin/card-audit" className="hover:text-neutral-100">
            Card audit
          </Link>
          <Link href="/admin/actions" className="hover:text-neutral-100">
            Actions
          </Link>
          <Link href="/admin/backup" className="hover:text-neutral-100">
            Backup
          </Link>
        </nav>
        <AuthControl />
      </div>
    </header>
  );
}

function AuthControl() {
  const { data: session, status } = useSession();

  if (status === "loading") {
    return <span className="text-xs text-neutral-600">…</span>;
  }

  if (!session) {
    return (
      <button
        type="button"
        onClick={() => signIn("google", { callbackUrl: "/dashboard" })}
        className="rounded bg-neutral-100 px-2.5 py-1 text-xs font-medium text-neutral-900 hover:bg-white"
      >
        Sign in with Google
      </button>
    );
  }

  return (
    <div className="flex items-center gap-2 text-xs text-neutral-400">
      <span className="max-w-[10rem] truncate" title={session.user?.email ?? undefined}>
        {session.user?.name || session.user?.email}
      </span>
      <button
        type="button"
        onClick={() => signOut({ callbackUrl: "/dashboard" })}
        className="rounded border border-neutral-700 px-2 py-1 font-medium text-neutral-300 hover:text-neutral-100"
      >
        Sign out
      </button>
    </div>
  );
}
