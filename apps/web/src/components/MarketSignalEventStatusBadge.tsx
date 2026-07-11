const STATUS_STYLES: Record<string, string> = {
  open: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  watching: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  dismissed: "bg-neutral-500/15 text-neutral-400 ring-neutral-500/30",
  resolved: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
};

const DEFAULT_STYLE = "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";

export function MarketSignalEventStatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? DEFAULT_STYLE;
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}
    >
      {status}
    </span>
  );
}
