import Link from "next/link";
import type { ReactNode } from "react";
import { AppHeader } from "@/components/AppHeader";
import styles from "./AdminShell.module.css";

export function AdminPageShell({ children }: { children: ReactNode }) {
  return <div className="min-h-screen"><AppHeader /><main className={styles.page}>{children}</main></div>;
}

export function AdminBreadcrumbs({ items }: { items: { label: string; href?: string }[] }) {
  return <nav aria-label="Breadcrumb" className={styles.breadcrumbs}>
    <Link href="/admin">Admin</Link>
    {items.map((item) => <span key={item.label} className="inline-flex items-center gap-2">
      <span aria-hidden="true">/</span>
      {item.href ? <Link href={item.href}>{item.label}</Link> : <span aria-current="page">{item.label}</span>}
    </span>)}
  </nav>;
}

export function AdminPageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return <header className={styles.pageHeader}><div className={styles.headingRow}><h1>{title}</h1>{actions}</div>{description && <p>{description}</p>}</header>;
}

export function AdminSection({ title, children }: { title: string; children: ReactNode }) {
  return <section className={styles.section}><h2>{title}</h2>{children}</section>;
}

export function AdminMetricStrip({ children }: { children: ReactNode }) {
  return <div className={styles.metrics}>{children}</div>;
}

export function AdminFilterPanel({ children, labelledBy }: { children: ReactNode; labelledBy: string }) {
  return <section aria-labelledby={labelledBy} className={styles.filters}>{children}</section>;
}

export function AdminStatusBadge({ children }: { children: ReactNode }) {
  return <span className={styles.status}>{children}</span>;
}
