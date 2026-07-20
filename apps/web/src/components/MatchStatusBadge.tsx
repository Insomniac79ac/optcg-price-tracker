const MATCH_STATUS_STYLES: Record<string, string> = {
  unmatched: "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30",
  matched: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  suggested: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  ambiguous: "bg-orange-500/15 text-orange-300 ring-orange-500/30",
  rejected: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
};

const DEFAULT_STYLE = "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";

export function MatchStatusBadge({ status }: { status: string }) {
  const style = MATCH_STATUS_STYLES[status] ?? DEFAULT_STYLE;
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}
    >
      {status}
    </span>
  );
}
