"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "next-auth/react";
import { useMemo, useState } from "react";

interface NavItem {
  href: string;
  label: string;
  children?: { href: string; label: string }[];
}

interface NavGroup {
  key: string;
  label: string;
  items: NavItem[];
  defaultCollapsed?: boolean;
}

// Public tier - visible to every visitor, signed in or not (collector-first
// redesign audit, Phase 3). "Cards" now points at the real /cards catalogue
// (image-led grid + Market Index) - /search still exists for the multi-type
// command-center search, but is no longer the primary card-browsing surface
// (see src/app/search/page.tsx's redirect). There is still no "Sets" entry -
// see collector-blueprint.pdf.
// Exported so TopBar's desktop public nav renders exactly this list rather
// than declaring a second one that could drift (or quietly gain an admin
// entry) - see components/ui/TopBar.tsx.
export const PUBLIC_NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Discover" },
  { href: "/cards", label: "Cards" },
  { href: "/market/movers", label: "Market Index" },
];

// Collector tier - only shown once a session exists. Trading/internal pages
// (Opportunities, Signals, Signal Events, Report, Buy/Sell Decisions,
// Portfolio Risk, and the rest of the old Analytics group) are deliberately
// left out of navigation here, pending a later product decision on where
// they belong - their routes still exist and are still reachable directly,
// just not linked from here or from the command palette (see
// commandRegistry.ts and CommandPalette.tsx).
const COLLECTOR_ITEMS: NavItem[] = [
  {
    href: "/collection",
    label: "My Collection",
    children: [{ href: "/collection/vault", label: "Vault View" }],
  },
  { href: "/wishlist", label: "Wishlist" },
  { href: "/grading", label: "Grading" },
  { href: "/activity", label: "Activity" },
];

// A role="admin" session gets exactly one entry here, not the full
// operational route list - the detailed admin sub-navigation (Catalog Ops,
// Cache, Job Locks, etc.) lives inside the admin area itself (see
// app/admin/(protected)/layout.tsx's AdminSubNav), not the main
// collector-facing sidebar. This keeps infrastructure-heavy navigation out
// of the surface every visitor sees.
const ADMIN_ITEMS: NavItem[] = [{ href: "/admin", label: "Admin" }];

function buildGroups(isAuthenticated: boolean, isAdmin: boolean): NavGroup[] {
  const groups: NavGroup[] = [{ key: "public", label: "Browse", items: PUBLIC_NAV_ITEMS }];
  if (isAuthenticated) {
    groups.push({ key: "collector", label: "Collector", items: COLLECTOR_ITEMS });
  }
  if (isAdmin) {
    groups.push({ key: "admin", label: "Admin", items: ADMIN_ITEMS });
  }
  return groups;
}

function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** The active treatment is teal-on-elevated with a teal edge, not just a
 * slightly lighter surface. `--bg-elevated` against the drawer's own
 * `--bg-surface` is a 4-value shift that is legible on a colour-managed
 * desktop panel and effectively invisible on a phone in daylight, which left
 * the mobile drawer with no clear indication of the current destination.
 * Teal is the design system's assigned navigation colour, so this reads the
 * same way in the drawer and in the header's PublicNav.
 *
 * `aria-current="page"` matches what TopBar's PublicNav already sets, so the
 * current destination is announced identically on both navigation surfaces. */
function NavLink({ href, label, active }: { href: string; label: string; active: boolean }) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`block truncate rounded-control border-l-2 px-2 py-1 text-[13px] transition-colors ${
        active
          ? "border-accent-teal bg-accent-teal/12 font-medium text-accent-teal-hover"
          : "border-transparent text-text-secondary hover:bg-bg-elevated/60 hover:text-text-primary"
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
          aria-current={active ? "page" : undefined}
          className={`block flex-1 truncate rounded-control border-l-2 px-2 py-1 text-[13px] transition-colors ${
            active
              ? "border-accent-teal bg-accent-teal/12 font-medium text-accent-teal-hover"
              : "border-transparent text-text-secondary hover:bg-bg-elevated/60 hover:text-text-primary"
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
  const { data: session, status } = useSession();
  const isAuthenticated = status === "authenticated";
  const isAdmin = session?.user?.role === "admin";
  const groups = useMemo(() => buildGroups(isAuthenticated, isAdmin), [isAuthenticated, isAdmin]);

  return (
    <div className={`overflow-y-auto py-3 ${className}`}>
      {groups.map((group, idx) => (
        <div key={group.key}>
          {idx > 0 && <div className="mx-4 my-1 border-t border-border-muted" />}
          <GroupBlock group={group} pathname={pathname} />
        </div>
      ))}
    </div>
  );
}
