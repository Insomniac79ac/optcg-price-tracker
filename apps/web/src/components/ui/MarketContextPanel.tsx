import Link from "next/link";

import { MarketSignalEventStatusBadge } from "@/components/MarketSignalEventStatusBadge";
import { OpportunityCategoryBadge } from "@/components/OpportunityCategoryBadge";
import { SeverityBadge } from "@/components/SeverityBadge";
import { EmptyState } from "@/components/StateBlocks";
import type { MarketOpportunity, MarketSignalEvent } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

/** Card-detail market-context panel - deterministic labels only, straight
 * from the existing signal-events/opportunities APIs (both already
 * card_code-filterable) - no new scoring or AI-generated recommendations. */
export function MarketContextPanel({
  signalEvents,
  opportunities,
}: {
  signalEvents: MarketSignalEvent[];
  opportunities: MarketOpportunity[];
}) {
  return (
    <div className="panel p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-text-primary">Market context</h2>
        <div className="flex flex-wrap gap-3 text-xs">
          <Link href="/market/opportunities" className="text-sky-400 hover:text-sky-300">
            Opportunities →
          </Link>
          <Link href="/analytics/buy-decisions" className="text-sky-400 hover:text-sky-300">
            Buy decisions →
          </Link>
          <Link href="/analytics/sell-decisions" className="text-sky-400 hover:text-sky-300">
            Sell decisions →
          </Link>
          <Link href="/analytics/portfolio-risk" className="text-sky-400 hover:text-sky-300">
            Portfolio risk →
          </Link>
        </div>
      </div>

      {opportunities.length === 0 && signalEvents.length === 0 ? (
        <EmptyState variant="inline">No active market signals for this card.</EmptyState>
      ) : (
        <div className="space-y-4">
          {opportunities.length > 0 && (
            <div>
              <div className="mb-1.5 text-[11px] uppercase tracking-wide text-text-secondary">
                Opportunities
              </div>
              <div className="flex flex-wrap gap-2">
                {opportunities.map((opp) => (
                  <span
                    key={opp.event_id}
                    className="flex items-center gap-1.5 rounded-control border border-border-default bg-bg-page px-2 py-1 text-xs"
                  >
                    <span className="mono tabular font-semibold text-text-primary">{opp.score}</span>
                    <OpportunityCategoryBadge category={opp.category} />
                  </span>
                ))}
              </div>
            </div>
          )}

          {signalEvents.length > 0 && (
            <div>
              <div className="mb-1.5 text-[11px] uppercase tracking-wide text-text-secondary">
                Signal events
              </div>
              <div className="space-y-1.5">
                {signalEvents.map((event) => (
                  <div
                    key={event.id}
                    className="flex flex-wrap items-center gap-2 rounded-control border border-border-default bg-bg-page px-2 py-1.5 text-xs"
                  >
                    <MarketSignalEventStatusBadge status={event.status} />
                    <SeverityBadge severity={event.severity} />
                    <span className="text-text-secondary">{event.signal_type}</span>
                    {event.suggested_action && (
                      <span className="text-text-muted">→ {event.suggested_action}</span>
                    )}
                    <span className="mono ml-auto text-[11px] text-text-faint">
                      {formatDateTime(event.last_seen_at)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
