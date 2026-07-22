import { PriceCell } from "./PriceCell";

export interface PriceLine {
  label: string;
  source?: string | null;
  priceType?: string | null;
  mode?: "raw_market" | "graded_adjusted" | null;
  valueJpy: number | null | undefined;
  observedAt?: string | null;
}

/** The 3-up key-price panel from cards/[id] (Yuyu-Tei sell/buy, SNKRDUNK
 * floor), generalized so any page can show a small set of "the prices that
 * matter" tiles with basis/staleness built in via PriceCell. */
export function CardPricePanel({ lines }: { lines: PriceLine[] }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {lines.map((line) => (
        <div key={line.label} className="panel p-3">
          <div className="mb-1.5 text-[11px] uppercase tracking-wide text-text-secondary">
            {line.label}
          </div>
          <PriceCell
            valueJpy={line.valueJpy}
            source={line.source}
            priceType={line.priceType}
            mode={line.mode}
            observedAt={line.observedAt}
          />
        </div>
      ))}
    </div>
  );
}
