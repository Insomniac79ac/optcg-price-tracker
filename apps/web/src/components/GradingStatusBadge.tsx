const GRADING_STATUS_STYLES: Record<string, string> = {
  planned: "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30",
  preparing: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  submitted: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  grading: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  shipped_back: "bg-cyan-500/15 text-cyan-300 ring-cyan-500/30",
  received: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  cancelled: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
};

const DEFAULT_STYLE = "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";

export function GradingStatusBadge({ status }: { status: string }) {
  const style = GRADING_STATUS_STYLES[status] ?? DEFAULT_STYLE;
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}
