import Link from "next/link";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/StateBlocks";
import { WishlistPriorityBadge } from "@/components/WishlistPriorityBadge";
import { WishlistStatusBadge } from "@/components/WishlistStatusBadge";
import type { WishlistItem } from "@/lib/api";
import { formatJpy, formatSignedJpy, formatSignedPct } from "@/lib/format";

/** Card-detail wishlist panel - priority/status/desired vs owned quantity/
 * target+max buy price/current price/target-hit/gap. `addAction` is the
 * caller's existing "+ Add to wishlist" quick-add form, always available. */
export function WishlistSummaryPanel({
  items,
  addAction,
}: {
  items: WishlistItem[];
  addAction?: ReactNode;
}) {
  return (
    <div className="panel p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-text-primary">Wishlist</h2>
        <Link href="/wishlist" className="text-xs text-sky-400 hover:text-sky-300">
          View wishlist →
        </Link>
      </div>

      {items.length === 0 && <EmptyState variant="inline">Not on wishlist.</EmptyState>}

      {items.length > 0 && (
        <div className="mb-3 space-y-3">
          {items.map((item) => (
            <div key={item.id} className="rounded-control border border-border-default bg-bg-page p-3">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
                <WishlistPriorityBadge priority={item.priority} />
                <WishlistStatusBadge status={item.status} />
                {item.target_hit && (
                  <span className="badge bg-signal-green/15 text-signal-green ring-1 ring-inset ring-signal-green/30">
                    target hit
                  </span>
                )}
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-text-secondary">
                    Desired / owned
                  </div>
                  <div className="mono tabular text-sm text-text-primary">
                    {item.desired_quantity} / {item.owned_quantity}
                  </div>
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-text-secondary">
                    Target buy
                  </div>
                  <div className="mono tabular text-sm text-text-primary">
                    {formatJpy(item.target_buy_price_jpy)}
                  </div>
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-text-secondary">
                    Max buy
                  </div>
                  <div className="mono tabular text-sm text-text-primary">
                    {formatJpy(item.max_buy_price_jpy)}
                  </div>
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-text-secondary">
                    Current price
                  </div>
                  <div className="mono tabular text-sm text-text-primary">
                    {formatJpy(item.preferred_current_price_jpy)}
                    {item.preferred_current_price_source && (
                      <span className="ml-1 text-[11px] text-text-muted">
                        ({item.preferred_current_price_source})
                      </span>
                    )}
                  </div>
                </div>
              </div>
              {item.gap_to_target_jpy !== null && (
                <div className="mt-2 text-xs text-text-muted">
                  Gap to target: {formatSignedJpy(item.gap_to_target_jpy)}
                  {item.gap_to_target_pct !== null && ` (${formatSignedPct(item.gap_to_target_pct)})`}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {addAction}
    </div>
  );
}
