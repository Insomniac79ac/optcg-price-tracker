"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { PUBLIC_NAV_ITEMS } from "./SidebarNav";
import { publicSectionActive } from "./publicNavigation";
import styles from "./PublicShell.module.css";

const ICON_PATHS: Record<string, string> = {
  "/": "M3 10 12 3 21 10 M5 9v12h5v-7h4v7h5V9",
  "/cards": "M5 7h11v15H5z M9 3h11v15",
  "/analytics": "M3 19 10 12 14 16 21 6 M15 6h6v6",
};

export function PublicBottomNav() {
  const pathname = usePathname() ?? "";
  return (
    <nav aria-label="Mobile public sections" data-public-bottom-nav="" className={styles.bottomNav}>
      {PUBLIC_NAV_ITEMS.map(({ href, label }) => (
        <Link key={href} href={href} prefetch={false} aria-current={publicSectionActive(pathname, href) ? "page" : undefined}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
            <path d={ICON_PATHS[href]} />
          </svg>
          <span>{label}</span>
        </Link>
      ))}
    </nav>
  );
}
