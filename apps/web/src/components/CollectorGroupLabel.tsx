import type { CollectorGroup } from "@/lib/api";

export function CollectorGroupLabel({
  group,
  onRemove,
}: {
  group: CollectorGroup;
  onRemove?: () => void;
}) {
  return (
    <span className="inline-flex items-center gap-1 rounded-sm border border-neutral-700 px-1.5 py-0.5 text-[10px] text-neutral-300">
      {group.name}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="leading-none text-neutral-500 hover:text-rose-400"
          aria-label={`Remove group ${group.name}`}
        >
          ×
        </button>
      )}
    </span>
  );
}
