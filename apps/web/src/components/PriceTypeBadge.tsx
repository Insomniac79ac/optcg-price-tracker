const PRICE_TYPE_STYLES: Record<string, string> = {
  sell: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  buy: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  floor: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  sold: "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30",
};

const DEFAULT_STYLE = "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";

export function PriceTypeBadge({ priceType }: { priceType: string }) {
  const style = PRICE_TYPE_STYLES[priceType] ?? DEFAULT_STYLE;
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}
    >
      {priceType}
    </span>
  );
}
