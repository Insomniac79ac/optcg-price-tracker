const LEVEL_STYLES: Record<string, string> = {
  debug: "bg-neutral-500/15 text-neutral-400 ring-neutral-500/30",
  info: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  warning: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  error: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  critical: "bg-rose-600/25 text-rose-200 ring-rose-500/50 font-semibold",
};

const DEFAULT_STYLE = "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";

export function LogLevelBadge({ level }: { level: string }) {
  const style = LEVEL_STYLES[level] ?? DEFAULT_STYLE;
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs uppercase tracking-wide ring-1 ring-inset ${style}`}
    >
      {level}
    </span>
  );
}
