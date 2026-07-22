import { Badge } from "./Badge";

const SOURCE_TONE: Record<string, string> = {
  yuyutei: "bg-sky-500/15 text-sky-300 ring-1 ring-inset ring-sky-500/30",
  snkrdunk: "bg-fuchsia-500/15 text-fuchsia-300 ring-1 ring-inset ring-fuchsia-500/30",
};

const SOURCE_LABELS: Record<string, string> = {
  yuyutei: "Yuyu-Tei",
  snkrdunk: "SNKRDUNK",
};

const PRICE_TYPE_LABELS: Record<string, string> = {
  sell: "sell",
  buy: "buy",
  floor: "floor",
  sold: "sold",
};

const MODE_LABELS: Record<string, string> = {
  raw_market: "Raw market",
  graded_adjusted: "Graded adjusted",
};

const MODE_TONE: Record<string, string> = {
  raw_market: "bg-neutral-500/15 text-neutral-300 ring-1 ring-inset ring-neutral-500/30",
  graded_adjusted: "bg-violet-500/15 text-violet-300 ring-1 ring-inset ring-violet-500/30",
};

const DEFAULT_TONE = "bg-neutral-500/15 text-neutral-300 ring-1 ring-inset ring-neutral-500/30";

/** Names the basis for a price so it's never a bare, ambiguous "Market"
 * value (design brief §5/§8) - either a source+price-type pair (e.g.
 * "Yuyu-Tei sell", "SNKRDUNK floor") or a valuation mode (Raw market /
 * Graded adjusted). Exactly one of `source` or `mode` should be passed. */
export function PriceBasisLabel({
  source,
  priceType,
  mode,
}: {
  source?: string | null;
  priceType?: string | null;
  mode?: "raw_market" | "graded_adjusted" | null;
}) {
  if (mode) {
    return <Badge label={MODE_LABELS[mode] ?? mode} className={MODE_TONE[mode] ?? DEFAULT_TONE} />;
  }
  if (source) {
    const typeLabel = priceType ? ` ${PRICE_TYPE_LABELS[priceType] ?? priceType}` : "";
    return (
      <Badge
        label={`${SOURCE_LABELS[source] ?? source}${typeLabel}`}
        className={SOURCE_TONE[source] ?? DEFAULT_TONE}
      />
    );
  }
  return <Badge label="Basis not available" className={DEFAULT_TONE} />;
}
