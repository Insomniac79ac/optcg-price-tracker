import { formatJpy, formatSignedJpy, formatSignedPct } from "@/lib/format";
import { PriceBasisLabel } from "./PriceBasisLabel";

const STALE_THRESHOLD_MS = 48 * 60 * 60 * 1000; // 48h

function isStale(observedAt?: string | null): boolean {
  if (!observedAt) return false;
  const t = new Date(observedAt).getTime();
  if (Number.isNaN(t)) return false;
  return Date.now() - t > STALE_THRESHOLD_MS;
}

/** The canonical trader-facing price display (design brief §5): always
 * shows a JPY value in mono/tabular numerals, a source/basis chip so
 * "Market" is never ambiguous, a stale badge when `observedAt` is old, and
 * "not available" (never a blank/null/undefined) when there's no price. */
export function PriceCell({
  valueJpy,
  signed = false,
  percent,
  source,
  priceType,
  mode,
  observedAt,
  size = "md",
}: {
  valueJpy: number | null | undefined;
  /** Color by sign (+green/-red) for P/L-style deltas; plain prices stay neutral. */
  signed?: boolean;
  percent?: number | null;
  source?: string | null;
  priceType?: string | null;
  mode?: "raw_market" | "graded_adjusted" | null;
  observedAt?: string | null;
  size?: "sm" | "md";
}) {
  const missing = valueJpy === null || valueJpy === undefined;
  const valueText = missing ? "not available" : signed ? formatSignedJpy(valueJpy) : formatJpy(valueJpy);

  let colorClass = "text-text-primary";
  if (missing) {
    colorClass = "price-muted";
  } else if (signed) {
    colorClass = valueJpy > 0 ? "price-positive" : valueJpy < 0 ? "price-negative" : "price-muted";
  }

  const stale = !missing && isStale(observedAt);
  const hasBasis = Boolean(source || mode);

  return (
    <div className={size === "sm" ? "text-xs" : "text-sm"}>
      <div className={`mono tabular font-medium ${colorClass}`}>
        {valueText}
        {!missing && percent !== undefined && percent !== null && (
          <span className="ml-1 text-text-muted">({formatSignedPct(percent)})</span>
        )}
      </div>
      {(hasBasis || stale) && (
        <div className="mt-0.5 flex items-center gap-1">
          {hasBasis && <PriceBasisLabel source={source} priceType={priceType} mode={mode} />}
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
