import type { MarketIndex } from "@/lib/api";
import { formatJpy } from "@/lib/format";
import { CoverageBadge } from "./CoverageBadge";

const STALE_THRESHOLD_MS = 48 * 60 * 60 * 1000; // 48h - display-only warning,
// separate from the server-side 7d/30d eligibility windows that already
// decided what counts toward index_value_jpy (see
// services/api/app/services/market_index.py "Source eligibility").

function isDisplayStale(observedAt: string | null): boolean {
  if (!observedAt) return false;
  const t = new Date(observedAt).getTime();
  if (Number.isNaN(t)) return false;
  return Date.now() - t > STALE_THRESHOLD_MS;
}

/** The primary collector-facing price on a catalogue tile/card-detail page
 * (design brief Phase 3/9) - a JPY value plus how many sources back it,
 * never a bare, ambiguous number. `index_value_jpy: null` always renders
 * "Index unavailable", never ¥0 - see app.services.market_index's "Never
 * substitute zero for unavailable values". */
export function MarketIndexValue({
  index,
  size = "md",
}: {
  index: MarketIndex;
  size?: "sm" | "md" | "lg";
}) {
  const missing = index.index_value_jpy === null;
  const valueClass =
    size === "lg" ? "text-2xl" : size === "sm" ? "text-sm" : "text-lg";
  const stale = !missing && isDisplayStale(index.freshest_observation_at);

  return (
    <div>
      <div className={`mono tabular font-semibold ${valueClass} ${missing ? "price-muted" : "text-text-primary"}`}>
        {missing ? "Index unavailable" : formatJpy(index.index_value_jpy)}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        <CoverageBadge coverageStatus={index.coverage_status} sourceCount={index.source_count} />
        {stale && (
          <span className="badge bg-signal-warning/15 text-signal-warning ring-1 ring-inset ring-signal-warning/30">
            stale
          </span>
        )}
      </div>
    </div>
  );
}
