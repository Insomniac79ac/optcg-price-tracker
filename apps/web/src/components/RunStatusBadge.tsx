const RUN_STATUS_STYLES: Record<string, string> = {
  running: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  completed: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  completed_with_warnings: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  failed: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
};

const DEFAULT_STYLE = "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";

export function RunStatusBadge({ status }: { status: string }) {
  const style = RUN_STATUS_STYLES[status] ?? DEFAULT_STYLE;
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}
    >
      {status}
    </span>
  );
}
