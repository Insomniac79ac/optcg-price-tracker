const WISHLIST_PRIORITY_STYLES: Record<string, string> = {
  low: "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30",
  medium: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  high: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  grail: "bg-fuchsia-500/15 text-fuchsia-300 ring-fuchsia-500/30",
};

const DEFAULT_STYLE = "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";

export function WishlistPriorityBadge({ priority }: { priority: string }) {
  const style = WISHLIST_PRIORITY_STYLES[priority] ?? DEFAULT_STYLE;
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}
    >
      {priority}
    </span>
  );
}
