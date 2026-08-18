"use client";

/** Shared offset/limit pagination bar for list pages (activity, admin logs,
 * signal events, opportunities, search, wishlist, grading, ...) - callers
 * own the offset/limit state and refetch on change; this component is just
 * the math (page count, has-more) and the buttons. Safe when `total` is 0
 * or the current offset is past the last page (an empty last page after a
 * filter change, say) - `hasPrev`/`hasNext` and the page count are all
 * clamped rather than going negative/NaN.
 *
 * Styled from the design tokens rather than raw `neutral-*` Tailwind. This
 * bar renders directly under the approved /cards catalogue grid, where a
 * #0a0a0a select and #737373 caption sat visibly outside the warm-charcoal
 * palette every surface around it uses; the token values are the nearest
 * equivalents, so the admin list pages that share it are unchanged in intent
 * and only pick up the same warm neutrals as their own panels. */

/** Shared so Previous and Next can never drift apart. `disabled` is stated
 * with both reduced opacity and `cursor-not-allowed`, since opacity alone on
 * a dark surface reads as "quiet" rather than "unavailable". */
const PAGER_BUTTON_CLASS =
  "rounded-control border border-border-default px-2 py-1 font-medium text-text-secondary transition-colors hover:text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:text-text-secondary";

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
  // Nothing to page through - the whole list already fits on one page, so
  // Previous/Next/page-count would always be a no-op. The result-count text
  // stays (still useful, e.g. "12 results"), only the actual controls hide.
  const showControls = total > limit;

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-text-muted">
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
              className="rounded-control border border-border-default bg-bg-page px-1.5 py-1 text-xs text-text-primary focus:border-accent-teal focus:outline-none focus:ring-1 focus:ring-accent-teal"
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
      {showControls && (
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onOffsetChange(Math.max(0, offset - limit))}
            disabled={!hasPrev}
            className={PAGER_BUTTON_CLASS}
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
            className={PAGER_BUTTON_CLASS}
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
