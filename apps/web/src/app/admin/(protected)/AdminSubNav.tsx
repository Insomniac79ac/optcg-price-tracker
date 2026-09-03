"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// The full operational admin route list - deliberately NOT in the main
// collector-facing SidebarNav (which shows a single "Admin" entry - see
// src/components/ui/SidebarNav.tsx), rendered only inside this route
// group's own layout so infrastructure-heavy navigation stays out of the
// surface every visitor sees.
const ADMIN_ROUTES: { href: string; label: string }[] = [
  { href: "/admin/catalog-ops", label: "Catalog Ops" },
  { href: "/admin/cards", label: "Cards" },
  { href: "/admin/import-validation", label: "Import Validation" },
  { href: "/admin/card-audit", label: "Card Audit" },
  { href: "/admin/card-duplicates", label: "Duplicates" },
  { href: "/admin/snkrdunk-candidates", label: "SNKRDUNK Candidates" },
  { href: "/admin/source-mapping-quality", label: "Source Mapping Quality" },
  { href: "/admin/catalog-coverage", label: "Catalog Coverage" },
  { href: "/admin/price-source-health", label: "Price Source Health" },
  { href: "/admin/system-check", label: "System Check" },
  { href: "/admin/actions", label: "Actions" },
  { href: "/admin/backup", label: "Backup" },
  { href: "/admin/collection-attempts", label: "Collection Attempts" },
  { href: "/admin/logs", label: "Logs" },
  { href: "/admin/performance", label: "Performance" },
  { href: "/admin/alerts", label: "Alerts" },
  { href: "/admin/cache", label: "Cache" },
  { href: "/admin/data-retention", label: "Data Retention" },
  { href: "/admin/file-jobs", label: "File Jobs" },
  { href: "/admin/job-locks", label: "Job Locks" },
  { href: "/admin/market-workflow-runs", label: "Workflow Runs" },
  { href: "/admin/refresh-runs", label: "Refresh Runs" },
  { href: "/admin/release-status", label: "Release Status" },
];

export function AdminSubNav() {
  const pathname = usePathname() ?? "";
  return (
    <nav className="border-b border-border-muted bg-bg-surface/50 px-4 py-2">
      <div className="mx-auto flex max-w-7xl flex-wrap gap-1.5 text-xs">
        <Link
          href="/admin"
          className={`rounded-control px-2 py-1 transition-colors ${
            pathname === "/admin"
              ? "bg-bg-elevated text-text-primary"
              : "text-text-secondary hover:bg-bg-elevated/60 hover:text-text-primary"
          }`}
        >
          Overview
        </Link>
        {ADMIN_ROUTES.map((route) => {
          const active = pathname === route.href || pathname.startsWith(`${route.href}/`);
          return (
            <Link
              key={route.href}
              href={route.href}
              className={`rounded-control px-2 py-1 transition-colors ${
                active
                  ? "bg-bg-elevated text-text-primary"
                  : "text-text-secondary hover:bg-bg-elevated/60 hover:text-text-primary"
              }`}
            >
              {route.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
