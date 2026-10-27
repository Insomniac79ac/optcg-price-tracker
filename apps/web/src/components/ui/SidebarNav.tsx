"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";

import { useCollectorSession } from "@/hooks/useCollectorSession";

import { PUBLIC_NAV_ITEMS, publicSectionActive, type NavItem } from "./publicNavigation";
import styles from "./PublicDrawer.module.css";

// Collector tier - only shown once a session exists. The old trading and
// analytics pages (grading, activity, dashboard, search, signals, buy/sell
// decisions, portfolio risk, digest) were deleted in Collector v1 S1.
const COLLECTOR_ITEMS: NavItem[] = [
  { href: "/collection", label: "My Collection" },
  { href: "/watchlist", label: "Watchlist" },
];

// A role="admin" session gets exactly one entry here, not the operational
// route list - admin sub-navigation lives inside the admin area itself
// (components/admin/AdminNavigation), never in the drawer every visitor sees.
const ADMIN_ITEMS: NavItem[] = [{ href: "/admin", label: "Admin" }];

function isActive(pathname: string, href: string): boolean {
  if (href === "/" || href === "/cards" || href === "/analytics") return publicSectionActive(pathname, href);
  return pathname === href || pathname.startsWith(`${href}/`);
}

function Section({ label, items, pathname }: { label: string; items: NavItem[]; pathname: string }) {
  return (
    <section className={styles.section} aria-label={label}>
      <h2 className={styles.label}>{label}</h2>
      <ul>
        {items.map((item) => (
          <li key={item.href}>
            <Link
              href={item.href}
              aria-current={isActive(pathname, item.href) ? "page" : undefined}
              className={styles.row}
            >
              {item.label}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The mobile drawer (AppShell, below `md`), in the public shell's palette and
 * type: flat sections, 48px rows, and the current destination marked with the
 * same gold rule the header nav uses. Signed in, it also carries Account and
 * Sign out, which leave the header below `sm` so the bar never wraps. */
export function SidebarNav({ className = "" }: { className?: string }) {
  const pathname = usePathname() ?? "";
  const { data: session, status } = useCollectorSession();
  const isAuthenticated = status === "authenticated";
  const isAdmin = session?.user?.role === "admin";
  const collectorItems = session?.sessionKind === "collector"
    ? [...COLLECTOR_ITEMS, { href: "/account", label: "Account" }]
    : COLLECTOR_ITEMS;

  return (
    <nav aria-label="Site navigation" data-mobile-drawer="" className={`${styles.drawer} ${className}`}>
      <Section label="Browse" items={PUBLIC_NAV_ITEMS} pathname={pathname} />
      {isAuthenticated && <Section label="Collector" items={collectorItems} pathname={pathname} />}
      {isAdmin && <Section label="Admin" items={ADMIN_ITEMS} pathname={pathname} />}
      {isAuthenticated && (
        <div className={styles.footer}>
          <button
            type="button"
            onClick={() => signOut({ callbackUrl: "/" })}
            title={session?.user?.name || session?.user?.email || undefined}
            className={styles.signOut}
          >
            Sign out
          </button>
        </div>
      )}
    </nav>
  );
}
