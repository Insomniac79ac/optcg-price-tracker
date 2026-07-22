"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { getRecentWorkflows, type RecentWorkflowEntry } from "@/lib/recentWorkflows";
import { formatDateTime } from "@/lib/format";

const SHORTCUT_PILLS: { label: string; href: string }[] = [
  { label: "Buy Decisions", href: "/analytics/buy-decisions" },
  { label: "Sell Decisions", href: "/analytics/sell-decisions" },
  { label: "Portfolio Risk", href: "/analytics/portfolio-risk" },
  { label: "Catalog Ops", href: "/admin/catalog-ops" },
];

/** Dashboard "Workflow Shortcuts" section (design brief - "Command palette
 * + workflow shortcuts"). Reads recent-workflow entries from localStorage
 * (client-only, see lib/recentWorkflows.ts) plus a handful of static
 * analytics/admin shortcut pills. Deliberately not a second command
 * palette - just quick links. Renders the static pills even with no recent
 * history, since they're useful on their own. */
export function WorkflowShortcutsSection() {
  const [recent, setRecent] = useState<RecentWorkflowEntry[] | null>(null);

  useEffect(() => {
    setRecent(getRecentWorkflows(5));
  }, []);

  return (
    <div className="mb-6">
      <h2 className="mb-2 text-sm font-semibold text-text-primary">Workflow Shortcuts</h2>
      <div className="mb-3 flex flex-wrap gap-2">
        {SHORTCUT_PILLS.map((pill) => (
          <Link
            key={pill.href}
            href={pill.href}
            className="rounded-control border border-border-default px-2.5 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:text-text-primary"
          >
            {pill.label}
          </Link>
        ))}
        <span className="mono self-center rounded border border-border-default px-1.5 py-0.5 text-[10px] text-text-faint">
          ⌘K for more
        </span>
      </div>

      {recent && recent.length > 0 && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {recent.map((entry) => (
            <Link
              key={`${entry.item_type}-${entry.route_path}-${entry.label}`}
              href={entry.route_path}
              className="vault-card flex items-center justify-between gap-2 px-3 py-2 text-sm"
            >
              <div className="min-w-0">
                <div className="truncate font-medium text-text-primary">{entry.label}</div>
                <div className="truncate text-[11px] text-text-muted">{entry.route_path}</div>
              </div>
              <span className="mono shrink-0 text-[11px] text-text-faint">
                {formatDateTime(entry.last_used_at)}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
