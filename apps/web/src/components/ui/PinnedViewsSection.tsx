"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { fetchSavedViews, type SavedView } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

// Friendly labels for the route_paths saved views can point at - kept in
// sync with SidebarNav's nav list, not auto-derived from it (that list is
// nav-structure-shaped, not a flat route->label map).
const ROUTE_LABELS: Record<string, string> = {
  "/analytics/buy-decisions": "Buy Decisions",
  "/analytics/sell-decisions": "Sell Decisions",
  "/analytics/portfolio-risk": "Portfolio Risk",
  "/analytics/wishlist": "Wishlist Analytics",
  "/analytics/collection": "Collection Analytics",
  "/analytics/grading": "Grading Analytics",
  "/analytics/digest": "Analytics Digest",
  "/admin/source-mapping-quality": "Source Mapping Quality",
  "/admin/catalog-coverage": "Catalog Coverage",
  "/admin/price-source-health": "Price Source Health",
  "/admin/card-duplicates": "Duplicates",
  "/admin/cards": "Cards",
  "/admin/snkrdunk-candidates": "SNKRDUNK Candidates",
  "/collection": "Collection",
  "/wishlist": "Wishlist",
  "/grading": "Grading",
  "/market/opportunities": "Market Opportunities",
  "/market/signals": "Market Signals",
  "/market/signal-events": "Market Signal Events",
};

/** Pinned saved views across every scope, for /dashboard and
 * /admin/catalog-ops. Links go to the plain route_path only - none of this
 * app's pages read filters from the URL (confirmed when SavedViewBar was
 * built), so a saved view's filters can't be pre-applied via a link click;
 * visiting the page and picking the view from its own SavedViewBar is the
 * only way to apply it today. Renders nothing while loading or when there
 * are no pinned views, rather than an empty-state box - this is a bonus
 * shortcut section, not a primary page area worth a loading skeleton. */
export function PinnedViewsSection({
  title = "Pinned Views",
  limit = 6,
}: {
  title?: string;
  limit?: number;
}) {
  const [views, setViews] = useState<SavedView[] | null>(null);

  useEffect(() => {
    fetchSavedViews({ pinned: true, limit })
      .then((res) => setViews(res.items))
      .catch(() => setViews([]));
  }, [limit]);

  if (!views || views.length === 0) return null;

  return (
    <div className="mb-6">
      <h2 className="mb-2 text-sm font-semibold text-text-primary">{title}</h2>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {views.map((view) => (
          <Link
            key={view.id}
            href={view.route_path}
            className="vault-card flex items-center justify-between gap-2 px-3 py-2 text-sm"
          >
            <div className="min-w-0">
              <div className="truncate font-medium text-text-primary">{view.name}</div>
              <div className="truncate text-[11px] text-text-muted">
                {ROUTE_LABELS[view.route_path] ?? view.route_path}
                {" · "}
                {view.scope}
              </div>
            </div>
            <span className="mono shrink-0 text-[11px] text-text-faint">
              {formatDateTime(view.last_used_at)}
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
