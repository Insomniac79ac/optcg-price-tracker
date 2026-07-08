const SOURCE_STYLES: Record<string, string> = {
  yuyutei: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  snkrdunk: "bg-fuchsia-500/15 text-fuchsia-300 ring-fuchsia-500/30",
};

const SOURCE_LABELS: Record<string, string> = {
  yuyutei: "Yuyu-Tei",
  snkrdunk: "SNKRDUNK",
};

const DEFAULT_STYLE = "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";

export function SourceBadge({ source }: { source: string }) {
  const style = SOURCE_STYLES[source] ?? DEFAULT_STYLE;
  const label = SOURCE_LABELS[source] ?? source;
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}
    >
      {label}
    </span>
  );
}
