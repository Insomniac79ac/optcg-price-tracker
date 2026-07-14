const SEARCH_TYPE_STYLES: Record<string, string> = {
  cards: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  collection: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  wishlist: "bg-fuchsia-500/15 text-fuchsia-300 ring-fuchsia-500/30",
  grading: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  notes: "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30",
  activity: "bg-cyan-500/15 text-cyan-300 ring-cyan-500/30",
  signals: "bg-orange-500/15 text-orange-300 ring-orange-500/30",
  opportunities: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  reports: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
};

const DEFAULT_STYLE = "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";

export function SearchTypeBadge({ type }: { type: string }) {
  const style = SEARCH_TYPE_STYLES[type] ?? DEFAULT_STYLE;
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ring-inset ${style}`}
    >
      {type}
    </span>
  );
}
