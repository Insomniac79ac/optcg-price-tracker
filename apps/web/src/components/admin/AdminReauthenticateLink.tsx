"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { adminLoginHref } from "@/lib/adminLoginUrl";

const linkClass = "inline-flex min-h-11 shrink-0 items-center rounded-control border border-accent-teal/50 px-2.5 text-xs font-medium text-accent-teal-hover focus-visible:outline-2 focus-visible:outline-accent-teal";

function RecoveryLink() {
  const path = usePathname();
  const search = useSearchParams().toString();
  return <Link className={linkClass} href={adminLoginHref(`${path}${search ? `?${search}` : ""}`, true)}>Sign in again</Link>;
}

export function AdminReauthenticateLink() {
  return <Suspense fallback={<Link className={linkClass} href={adminLoginHref("/admin", true)}>Sign in again</Link>}><RecoveryLink /></Suspense>;
}
