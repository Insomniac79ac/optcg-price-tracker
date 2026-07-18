"use client";

/** Shared offset/limit pagination bar for list pages (activity, admin logs,
 * signal events, opportunities, search, wishlist, grading, ...) - callers
 * own the offset/limit state and refetch on change; this component is just
 * the math (page count, has-more) and the buttons. Safe when `total` is 0
 * or the current offset is past the last page (an empty last page after a
 * filter change, say) - `hasPrev`/`hasNext` and the page count are all
 * clamped rather than going negative/NaN. */
export function PaginationControls({
  offset,
  limit,
  total,
  onOffsetChange,
  limitOptions,
  onLimitChange,
}: {
  offset: number;
  limit: number;
  total: number;
  onOffsetChange: (offset: number) => void;
  limitOptions?: readonly number[];
  onLimitChange?: (limit: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / Math.max(1, limit)));
  const currentPage = Math.min(totalPages, Math.floor(offset / Math.max(1, limit)) + 1);
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-neutral-500">
      <div className="flex items-center gap-3">
        <span>
          {total === 0
            ? "0 results"
            : `${offset + 1}–${Math.min(offset + limit, total)} of ${total}`}
        </span>
        {onLimitChange && limitOptions && limitOptions.length > 0 && (
          <label className="flex items-center gap-1.5">
            Per page
            <select
              value={limit}
              onChange={(e) => onLimitChange(Number(e.target.value))}
              className="rounded border border-neutral-700 bg-neutral-950 px-1.5 py-1 text-xs text-neutral-100"
            >
              {limitOptions.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onOffsetChange(Math.max(0, offset - limit))}
          disabled={!hasPrev}
          className="rounded border border-neutral-700 px-2 py-1 font-medium text-neutral-300 hover:text-neutral-100 disabled:opacity-40"
        >
          Previous
        </button>
        <span>
          Page {currentPage} of {totalPages}
        </span>
        <button
          type="button"
          onClick={() => hasNext && onOffsetChange(offset + limit)}
          disabled={!hasNext}
          className="rounded border border-neutral-700 px-2 py-1 font-medium text-neutral-300 hover:text-neutral-100 disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  );
}
