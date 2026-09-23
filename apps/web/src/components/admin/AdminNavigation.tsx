"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";
import { ADMIN_NAVIGATION, adminRouteActive } from "./adminNavigation";
import styles from "./AdminShell.module.css";

export function AdminNavigation() {
  const pathname = usePathname() ?? "";
  return <nav aria-label="Admin navigation" className={styles.navigation}>
    <p className={styles.navTitle}>Administrator workspace</p>
    {ADMIN_NAVIGATION.map((group) => (
      <details key={`${group.label}:${pathname}`} open={group.routes.some(([href]) => adminRouteActive(pathname, href))}>
        <summary>{group.label}</summary>
        {group.routes.map(([href, label]) => <Link key={href} href={href} prefetch={false} aria-current={adminRouteActive(pathname, href) ? "page" : undefined}>{label}</Link>)}
      </details>
    ))}
  </nav>;
}

// Native modal dialog supplies focus containment, Escape and focus restoration.
export function AdminNavigationDrawer({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      dialog?.close();
      document.body.style.overflow = previousOverflow;
    };
  }, []);
  return <dialog ref={ref} className={styles.drawer} aria-label="Admin navigation drawer" onCancel={onClose}
    onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className={styles.drawerHeader}><span className="text-sm font-semibold">Atlas Admin</span><button type="button" onClick={onClose} aria-label="Close admin navigation">✕</button></div>
    <AdminNavigation />
  </dialog>;
}
