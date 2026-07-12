import type { CollectorTag } from "@/lib/api";

const DEFAULT_STYLE = "bg-neutral-500/15 text-neutral-300 ring-neutral-500/30";

export function CollectorTagBadge({
  tag,
  onRemove,
}: {
  tag: CollectorTag;
  onRemove?: () => void;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${
        tag.color ? "" : DEFAULT_STYLE
      }`}
      style={
        tag.color
          ? {
              backgroundColor: `${tag.color}26`,
              color: tag.color,
              boxShadow: `inset 0 0 0 1px ${tag.color}66`,
            }
          : undefined
      }
    >
      {tag.name}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="leading-none text-neutral-500 hover:text-rose-400"
          aria-label={`Remove tag ${tag.name}`}
        >
          ×
        </button>
      )}
    </span>
  );
}
