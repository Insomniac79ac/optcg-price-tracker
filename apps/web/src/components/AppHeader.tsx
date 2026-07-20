"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { signIn, signOut, useSession } from "next-auth/react";

const PRIMARY_LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/search", label: "Search", title: "Search (Ctrl/Cmd+K)" },
  { href: "/collection", label: "Collection" },
  { href: "/analytics/collection", label: "Collection analytics" },
  { href: "/analytics/portfolio-risk", label: "Portfolio risk" },
  { href: "/analytics/digest", label: "Digest" },
  { href: "/wishlist", label: "Wishlist" },
  { href: "/analytics/wishlist", label: "Wishlist analytics" },
  { href: "/analytics/buy-decisions", label: "Buy decisions" },
  { href: "/analytics/sell-decisions", label: "Sell decisions" },
  { href: "/grading", label: "Grading" },
  { href: "/analytics/grading", label: "Grading analytics" },
  { href: "/activity", label: "Activity" },
  { href: "/market/report", label: "Market report" },
  { href: "/market/opportunities", label: "Opportunities" },
  { href: "/market/signals", label: "Signals" },
  { href: "/market/signal-events", label: "Signal events" },
];

const ADMIN_LINKS = [
  { href: "/admin/actions", label: "Actions" },
  { href: "/admin/refresh-runs", label: "Refresh runs" },
  { href: "/admin/market-workflow-runs", label: "Workflow runs" },
  { href: "/admin/backup", label: "Backup" },
  { href: "/admin/system-check", label: "System check" },
  { href: "/admin/performance", label: "Performance" },
  { href: "/admin/cache", label: "Cache" },
  { href: "/admin/file-jobs", label: "File jobs" },
  { href: "/admin/job-locks", label: "Job locks" },
  { href: "/admin/data-retention", label: "Data retention" },
  { href: "/admin/release-status", label: "Release status" },
  { href: "/admin/logs", label: "App logs" },
  { href: "/admin/snkrdunk-candidates", label: "SNKRDUNK candidates" },
  { href: "/admin/alerts", label: "Alerts" },
  { href: "/admin/card-audit", label: "Card audit" },
  { href: "/admin/source-mapping-quality", label: "Mapping quality" },
  { href: "/admin/cards", label: "Card catalog" },
  { href: "/admin/card-duplicates", label: "Card duplicates" },
  { href: "/market/movers", label: "Market movers" },
];

export function AppHeader() {
  const router = useRouter();

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        router.push("/search");
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [router]);

  return (
    <header className="sticky top-0 z-10 border-b border-neutral-800 bg-neutral-950/95 backdrop-blur">
      <div className="mx-auto flex h-12 max-w-7xl items-center gap-6 px-4">
        <Link
          href="/dashboard"
          className="text-sm font-semibold tracking-tight text-neutral-100"
        >
          OPTCG Price Tracker
        </Link>
        <nav className="flex flex-1 items-center gap-4 overflow-x-auto text-sm text-neutral-400">
          {PRIMARY_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              title={link.title}
              className="shrink-0 hover:text-neutral-100"
            >
              {link.label}
            </Link>
          ))}
          <AdminMenu />
        </nav>
        <AuthControl />
      </div>
    </header>
  );
}

function AdminMenu() {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  return (
    <div ref={containerRef} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-1 ${open ? "text-neutral-100" : "hover:text-neutral-100"}`}
      >
        Admin
        <span className="text-[10px]">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="absolute right-0 top-full z-20 mt-2 w-48 rounded-lg border border-neutral-800 bg-neutral-900 py-1 shadow-lg">
          {ADMIN_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              onClick={() => setOpen(false)}
              className="block px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-800 hover:text-neutral-100"
            >
              {link.label}
            </Link>
          ))}
        </div>
      )}
    </div>
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
