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

/** The subset of a Market Index this component actually renders. Both the
 * legacy card-keyed `MarketIndex` and the print-scoped `PrintMarketIndex`
 * (see src/lib/prints.ts) satisfy it, so a print tile and a legacy card tile
 * can share one price component without either one widening to the other's
 * key (`card_id` vs `card_print_id`). */
export type MarketIndexDisplay = Pick<
  MarketIndex,
  "index_value_jpy" | "coverage_status" | "source_count" | "freshest_observation_at"
>;

/** The primary collector-facing price on a catalogue tile/card-detail page
 * (design brief Phase 3/9) - a JPY value plus how many sources back it,
 * never a bare, ambiguous number. `index_value_jpy: null` always renders
 * "Index unavailable", never ¥0 - see app.services.market_index's "Never
 * substitute zero for unavailable values".
 *
 * `sourceNames` is forwarded to CoverageBadge so a limited-coverage print can
 * name the one source backing it.
 *
 * `tone` and `showCoverage` are additive presentation options for the
 * collector catalogue tile, which wants the value read as *the* price on the
 * tile (gold, with its own inline caption) and states its coverage by listing
 * the real per-source prices underneath instead of a chip. Both default to
 * the previous behaviour, so the legacy card-detail page renders exactly as
 * before. The "never show ¥0 for a missing index" rule
 * stays in this one component whichever options are passed. */
export function MarketIndexValue({
  index,
  size = "md",
  sourceNames,
  tone = "default",
  showCoverage = true,
}: {
  index: MarketIndexDisplay;
  size?: "sm" | "base" | "md" | "lg";
  sourceNames?: string[];
  /** "gold" is the collector-catalogue emphasis; "default" is off-white. */
  tone?: "default" | "gold";
  /** Set false when the caller presents coverage itself. The stale warning
   * is not part of this and always renders when it applies. */
  showCoverage?: boolean;
}) {
  const missing = index.index_value_jpy === null;
  // "base" is the catalogue tile's step: 18px, the largest type anywhere on
  // a tile, so the index is unmistakably the tile's monetary focal point
  // against a 14px name and a 13px source price - with its leading trimmed so
  // the size buys presence rather than tile height. It matches "md" in size
  // but not in leading, and the other three keep their default leading and
  // their existing call sites unchanged.
  //
  // The step is for a *number*. "Index unavailable" is a sentence, not a
  // figure, so it stays at "sm": at "base" it wrapped to two loud lines in a
  // catalogue tile and gave an absence more presence than the real prices
  // beside it. The copy itself is unchanged, and a missing index is still
  // never rendered as ¥0.
  const valueClass =
    size === "lg"
      ? "text-2xl"
      : size === "md"
        ? "text-lg"
        : size === "base" && !missing
          ? "text-lg leading-none"
          : "text-sm";
  const stale = !missing && isDisplayStale(index.freshest_observation_at);
  const presentClass = tone === "gold" ? "text-accent-gold" : "text-text-primary";

  return (
    <div>
      <div
        className={`mono tabular font-semibold ${valueClass} ${
          missing ? "price-muted" : presentClass
        }`}
      >
        {missing ? "Index unavailable" : formatJpy(index.index_value_jpy)}
      </div>
      {(showCoverage || stale) && (
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          {showCoverage && (
            <CoverageBadge
              coverageStatus={index.coverage_status}
              sourceCount={index.source_count}
              sourceNames={sourceNames}
            />
          )}
          {stale && (
            <span className="badge bg-signal-warning/15 text-signal-warning ring-1 ring-inset ring-signal-warning/30">
              stale
            </span>
          )}
        </div>
      )}
    </div>
  );
}
