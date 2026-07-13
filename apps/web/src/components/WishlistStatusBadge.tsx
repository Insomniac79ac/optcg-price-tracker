const WISHLIST_STATUS_STYLES: Record<string, string> = {
  watching: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  target_hit: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  purchased: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  passed: "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30",
  removed: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
};

const DEFAULT_STYLE = "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";

export function WishlistStatusBadge({ status }: { status: string }) {
  const style = WISHLIST_STATUS_STYLES[status] ?? DEFAULT_STYLE;
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}
