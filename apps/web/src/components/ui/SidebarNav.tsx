"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

interface NavItem {
  href: string;
  label: string;
  children?: { href: string; label: string }[];
}

interface NavGroup {
  key: string;
  label: string;
  items: NavItem[];
  /** Collapsed groups are for existing routes the design brief didn't call
   * out by name (see docs/interface_design_system.md "nav mapping" note) -
   * kept reachable, just deprioritized visually. */
  defaultCollapsed?: boolean;
}

// Collector section - the brief's exact list, in order. Analytics routes
// (analytics/collection, analytics/wishlist, analytics/grading, and the
// top-level analytics/* pages) live in their own ANALYTICS_ITEMS group below
// rather than nested here, so the mobile nav drawer can clearly separate
// Collector / Analytics / Admin per the design brief.
const COLLECTOR_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/search", label: "Cards / Search" },
  {
    href: "/collection",
    label: "Collection",
    children: [{ href: "/collection/vault", label: "Vault View" }],
  },
  { href: "/wishlist", label: "Wishlist" },
  { href: "/grading", label: "Grading" },
  { href: "/activity", label: "Activity" },
  {
    href: "/market/report",
    label: "Market",
    children: [
      { href: "/market/report", label: "Report" },
      { href: "/market/opportunities", label: "Opportunities" },
      { href: "/market/signals", label: "Signals" },
      { href: "/market/signal-events", label: "Signal events" },
      { href: "/market/movers", label: "Movers" },
    ],
  },
];

// Analytics section - its own group (not nested under Collector) so the
// mobile drawer separates Collector / Analytics / Admin clearly.
const ANALYTICS_ITEMS: NavItem[] = [
  { href: "/analytics/digest", label: "Analytics Digest" },
  { href: "/analytics/collection", label: "Collection Analytics" },
  { href: "/analytics/wishlist", label: "Wishlist Analytics" },
  { href: "/analytics/grading", label: "Grading Analytics" },
  { href: "/analytics/buy-decisions", label: "Buy Decisions" },
  { href: "/analytics/sell-decisions", label: "Sell Decisions" },
  { href: "/analytics/portfolio-risk", label: "Portfolio Risk" },
];

// Admin section - the brief's exact list. "Source Mappings" is omitted: no
// route exists for it separately from source-mapping-quality (see plan /
// docs note - "do not invent route links if they do not exist").
const ADMIN_ITEMS: NavItem[] = [
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
  { href: "/admin/logs", label: "Logs" },
  { href: "/admin/performance", label: "Performance" },
];

// Existing admin routes the brief didn't name - kept reachable in a
// collapsed "More" group instead of being removed from navigation.
const ADMIN_MORE_ITEMS: NavItem[] = [
  { href: "/admin/alerts", label: "Alerts" },
  { href: "/admin/cache", label: "Cache" },
  { href: "/admin/data-retention", label: "Data Retention" },
  { href: "/admin/file-jobs", label: "File Jobs" },
  { href: "/admin/job-locks", label: "Job Locks" },
  { href: "/admin/market-workflow-runs", label: "Workflow Runs" },
  { href: "/admin/refresh-runs", label: "Refresh Runs" },
  { href: "/admin/release-status", label: "Release Status" },
];

const GROUPS: NavGroup[] = [
  { key: "collector", label: "Collector", items: COLLECTOR_ITEMS },
  { key: "analytics", label: "Analytics", items: ANALYTICS_ITEMS },
  { key: "admin", label: "Admin", items: ADMIN_ITEMS },
  { key: "admin-more", label: "Admin · More", items: ADMIN_MORE_ITEMS, defaultCollapsed: true },
];

function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavLink({ href, label, active }: { href: string; label: string; active: boolean }) {
  return (
    <Link
      href={href}
      className={`block truncate rounded-control px-2 py-1 text-[13px] transition-colors ${
        active
          ? "bg-bg-elevated text-text-primary"
          : "text-text-secondary hover:bg-bg-elevated/60 hover:text-text-primary"
      }`}
    >
      {label}
    </Link>
  );
}

function NavItemBlock({ item, pathname }: { item: NavItem; pathname: string }) {
  const active = isActive(pathname, item.href);
  const childActive = item.children?.some((c) => isActive(pathname, c.href)) ?? false;
  const [open, setOpen] = useState(active || childActive);

  if (!item.children) {
    return <NavLink href={item.href} label={item.label} active={active} />;
  }

  return (
    <div>
      <div className="flex items-center gap-1">
        <Link
          href={item.href}
          className={`block flex-1 truncate rounded-control px-2 py-1 text-[13px] transition-colors ${
            active
              ? "bg-bg-elevated text-text-primary"
              : "text-text-secondary hover:bg-bg-elevated/60 hover:text-text-primary"
          }`}
        >
          {item.label}
        </Link>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? `Collapse ${item.label}` : `Expand ${item.label}`}
          className="shrink-0 rounded px-1 text-[10px] text-text-faint hover:text-text-secondary"
        >
          {open ? "▾" : "▸"}
        </button>
      </div>
      {open && (
        <div className="ml-2 mt-0.5 space-y-0.5 border-l border-border-muted pl-2">
          {item.children.map((child) => (
            <NavLink
              key={child.href}
              href={child.href}
              label={child.label}
              active={isActive(pathname, child.href)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function GroupBlock({ group, pathname }: { group: NavGroup; pathname: string }) {
  const groupActive = group.items.some(
    (i) => isActive(pathname, i.href) || i.children?.some((c) => isActive(pathname, c.href)),
  );
  const [open, setOpen] = useState(!group.defaultCollapsed || groupActive);

  return (
    <div className="px-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="mb-1 flex w-full items-center justify-between px-2 text-[11px] font-semibold uppercase tracking-wide text-text-faint hover:text-text-muted"
      >
        <span>{group.label}</span>
        <span className="text-[9px]">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <nav className="space-y-0.5 pb-3">
          {group.items.map((item) => (
            <NavItemBlock key={item.href} item={item} pathname={pathname} />
          ))}
        </nav>
      )}
    </div>
  );
}

export function SidebarNav({ className = "" }: { className?: string }) {
  const pathname = usePathname() ?? "";
  return (
    <div className={`overflow-y-auto py-3 ${className}`}>
      {GROUPS.map((group, idx) => (
        <div key={group.key}>
          {idx > 0 && <div className="mx-4 my-1 border-t border-border-muted" />}
          <GroupBlock group={group} pathname={pathname} />
        </div>
      ))}
    </div>
  );
}
