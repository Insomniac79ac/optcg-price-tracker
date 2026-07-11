const CATEGORY_STYLES: Record<string, string> = {
  buy: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  sell: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  momentum: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  drop: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  data_quality: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  owned: "bg-cyan-500/15 text-cyan-300 ring-cyan-500/30",
};

const DEFAULT_STYLE = "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";

export function OpportunityCategoryBadge({ category }: { category: string }) {
  const style = CATEGORY_STYLES[category] ?? DEFAULT_STYLE;
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}
    >
      {category.replace("_", " ")}
    </span>
  );
}
