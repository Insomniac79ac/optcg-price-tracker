const RARITY_STYLES: Record<string, string> = {
  L: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  SEC: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  SR: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  R: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  UC: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  C: "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30",
};

const DEFAULT_STYLE = "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";

export function RarityBadge({ rarity }: { rarity: string }) {
  const style = RARITY_STYLES[rarity] ?? DEFAULT_STYLE;
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}
    >
      {rarity}
    </span>
  );
}
