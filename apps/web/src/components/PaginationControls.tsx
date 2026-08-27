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
 * and only pick up the same warm neutrals as their own panels.
 *
 * TWO PRESENTATIONS, ONE SET OF MECHANICS. `variant` changes layout and
 * emphasis only. The offsets `onOffsetChange` receives, the `hasPrev`/
 * `hasNext` disabled rules, the page maths and the "nothing to page through"
 * rule are computed once above the branch and are identical in both, so a
 * catalogue and an admin table can never disagree about what page they are
 * on. There is deliberately no second pagination component: the reason the
 * public catalogue's bar was invisible was presentation, and duplicating the
 * logic to fix presentation is how the two drift apart.
 *
 *   "default"   - the dense caption-weight bar every list page has today.
 *                 Range text left, controls right. Unchanged, and it stays
 *                 the default so no existing call site is touched.
 *   "catalogue" - the public /cards catalogue. See CATALOGUE VARIANT below.
 */

/** Shared so Previous and Next can never drift apart. `disabled` is stated
 * with both reduced opacity and `cursor-not-allowed`, since opacity alone on
 * a dark surface reads as "quiet" rather than "unavailable". */
const PAGER_BUTTON_CLASS =
  "rounded-control border border-border-default px-2 py-1 font-medium text-text-secondary transition-colors hover:text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:text-text-secondary";

/** CATALOGUE VARIANT - the same button, sized to be seen and tapped.
 *
 * The public catalogue is 179 pages long and most of it is read on a phone,
 * where the default bar's 26px-tall, 12px, #8b8672 controls sat at the far
 * right of a 1248px row from the range text at the far left and read as a
 * footer caption rather than as the way through the catalogue.
 *
 * So: `min-h-11`/`min-w-11` is 44px in both axes - the minimum touch target,
 * asserted in the tests rather than left to survive a future padding tweak by
 * luck. The elevated surface and a border that warms to teal on hover state
 * "control" the way the muted text-only version did not. Everything else -
 * the focus ring, the disabled treatment - is the default's, unchanged,
 * because those were already right. */
const CATALOGUE_BUTTON_CLASS =
  "inline-flex min-h-11 min-w-11 items-center justify-center rounded-control border border-border-default bg-bg-elevated px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent-teal hover:text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 disabled:cursor-not-allowed disabled:border-border-muted disabled:bg-transparent disabled:text-text-muted disabled:opacity-60 disabled:hover:border-border-muted";

export type PaginationVariant = "default" | "catalogue";

export function PaginationControls({
  offset,
  limit,
  total,
  onOffsetChange,
  limitOptions,
  onLimitChange,
  variant = "default",
}: {
  offset: number;
  limit: number;
  total: number;
  onOffsetChange: (offset: number) => void;
  limitOptions?: readonly number[];
  onLimitChange?: (limit: number) => void;
  /** Presentation only - see the module docstring. Defaults to the dense
   * list-page bar, so every existing admin/internal call site renders exactly
   * as it did before this prop existed. */
  variant?: PaginationVariant;
}) {
  const totalPages = Math.max(1, Math.ceil(total / Math.max(1, limit)));
  const currentPage = Math.min(totalPages, Math.floor(offset / Math.max(1, limit)) + 1);
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;
  // Nothing to page through - the whole list already fits on one page, so
  // Previous/Next/page-count would always be a no-op. The result-count text
  // stays (still useful, e.g. "12 results"), only the actual controls hide.
  const showControls = total > limit;
  const goPrev = () => onOffsetChange(Math.max(0, offset - limit));
  const goNext = () => hasNext && onOffsetChange(offset + limit);

  if (variant === "catalogue") {
    return (
      // A real landmark, not a styled div: on a page whose main content is a
      // 24-tile grid, "Catalogue pagination" is how a screen-reader user finds
      // the way to page 2 without walking every tile. The top border and the
      // padding above it are the whole point of the section - they separate
      // the controls from the last row of artwork, which is what stopped this
      // reading as navigation. In normal flow, never sticky or floating.
      <nav
        aria-label="Catalogue pagination"
        className="border-t border-border-muted pt-6 pb-2"
      >
        {showControls && (
          // A symmetric three-column grid, not a centred flex row, and the
          // reason is measurable: "Previous" is 91px wide and "Next" is 65px,
          // so a flex row centred as a group leaves the page status 13px to
          // the right of the container's centre - and 13px out of true from
          // the "Showing ..." line directly beneath it, which is centred over
          // the full width. Equal side columns put the status on the page's
          // real centre axis, and keep it there whatever the two labels
          // measure. Capped at max-w-md so the controls stay a group on a
          // 1248px row instead of drifting to the far edges.
          <div className="mx-auto grid w-full max-w-md grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-x-3 sm:gap-x-4">
            <button
              type="button"
              onClick={goPrev}
              disabled={!hasPrev}
              className={`${CATALOGUE_BUTTON_CLASS} justify-self-end`}
            >
              Previous
            </button>
            {/* The most prominent text in the bar, and centred between the two
                controls it describes: primary foreground at 16px against the
                12px muted range line below it. The min-width holds the column
                steady so the buttons don't shift sideways between "Page 1 of
                179" and "Page 179 of 179". `aria-live` announces the move to a
                screen reader, which otherwise gets no signal that the grid
                behind it was replaced. */}
            <p
              aria-live="polite"
              className="min-w-[8.5rem] text-center text-base font-medium text-text-primary"
            >
              Page {currentPage} of {totalPages}
            </p>
            <button
              type="button"
              onClick={goNext}
              disabled={!hasNext}
              className={`${CATALOGUE_BUTTON_CLASS} justify-self-start`}
            >
              Next
            </button>
          </div>
        )}
        {/* Secondary, and secondary on purpose: which page you are on is the
            navigational fact, how many results there are is context. Read
            straight off the same `offset`/`limit`/`total` the buttons use -
            no second request, no new field. Thousands separators only here,
            where the number is prose a collector reads ("of 4,281"); the
            dense variant keeps its bare digits. */}
        <p
          className={`text-center text-xs text-text-muted ${showControls ? "mt-3" : ""}`}
        >
          {total === 0
            ? "0 results"
            : `Showing ${(offset + 1).toLocaleString("en-US")}–${Math.min(
                offset + limit,
                total,
              ).toLocaleString("en-US")} of ${total.toLocaleString("en-US")}`}
        </p>
      </nav>
    );
  }

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
            onClick={goPrev}
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
            onClick={goNext}
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
