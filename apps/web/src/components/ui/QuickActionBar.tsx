"use client";

import Link from "next/link";

import { ActionButton, type ActionButtonVariant } from "./ActionButton";

export interface QuickAction {
  label: string;
  /** Either a navigable href, or an onClick calling a handler the page
   * already owns (e.g. an existing dry-run/bulk-preview function, or a
   * scrollIntoView onto an existing on-page form). Never both. */
  href?: string;
  onClick?: () => void;
  variant?: ActionButtonVariant;
}

/** Deliberately dumb row of shortcut pills for a page's most common
 * workflows (design brief - "Workflow shortcuts"). Never contains its own
 * mutation logic - the calling page supplies real hrefs/handlers it already
 * has. See docs/interface_design_system.md "QuickActionBar". */
export function QuickActionBar({ actions, className = "" }: { actions: QuickAction[]; className?: string }) {
  if (actions.length === 0) return null;

  return (
    <div className={`mb-4 flex flex-wrap items-center gap-2 ${className}`}>
      {actions.map((action) =>
        action.href ? (
          <Link
            key={action.label}
            href={action.href}
            className="rounded-control border border-border-default px-2.5 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:text-text-primary"
          >
            {action.label}
          </Link>
        ) : (
          <ActionButton key={action.label} variant={action.variant ?? "default"} onClick={action.onClick}>
            {action.label}
          </ActionButton>
        ),
      )}
    </div>
  );
}
