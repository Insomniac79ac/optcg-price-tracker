import { formatJpy } from "@/lib/format";
import { PriceCell } from "./PriceCell";
import type { PriceLine } from "./CardPricePanel";

/** Side-by-side source comparison (Yuyu-Tei vs SNKRDUNK, etc.) with the
 * spread between the highest and lowest observed price called out - the
 * trader-facing "which source is cheaper right now" view. */
export function SourceComparisonPanel({ lines, title = "Source comparison" }: { lines: PriceLine[]; title?: string }) {
  const numericValues = lines
    .map((l) => l.valueJpy)
    .filter((v): v is number => v !== null && v !== undefined);
  const spread =
    numericValues.length >= 2 ? Math.max(...numericValues) - Math.min(...numericValues) : null;

  return (
    <div className="panel p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-medium text-text-primary">{title}</div>
        {spread !== null && (
          <div className="text-xs text-text-secondary">
            Spread: <span className="mono tabular text-text-primary">{formatJpy(spread)}</span>
          </div>
        )}
      </div>
      <div className="divide-y divide-border-muted">
        {lines.map((line) => (
          <div key={line.label} className="flex items-center justify-between gap-3 py-2 first:pt-0 last:pb-0">
            <span className="text-xs text-text-secondary">{line.label}</span>
            <PriceCell
              valueJpy={line.valueJpy}
              source={line.source}
              priceType={line.priceType}
              mode={line.mode}
              observedAt={line.observedAt}
              size="sm"
            />
          </div>
        ))}
      </div>
    </div>
  );
}
