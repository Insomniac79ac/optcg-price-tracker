import type { CSSProperties, ReactNode } from "react";

import { EmptyState } from "@/components/StateBlocks";

/** Outer scroll chrome for a wide table: horizontal (and capped vertical)
 * scroll inside its own container - never the whole page - a CSS-only fade
 * at the leading/trailing edge once there's more to scroll to (see
 * `.table-scroll-fade` in globals.css), and an optional one-line "scroll
 * horizontally" hint for mobile. `minWidth` keeps dense admin/analytics
 * tables from squishing illegibly on narrow screens - they scroll instead of
 * shrinking every column to fit. */
export function TableScrollContainer({
  children,
  minWidth,
  showScrollHint = true,
  className = "",
}: {
  children: ReactNode;
  /** e.g. 960 or "60rem" - applied to an inner wrapper so the table itself
   * never has to shrink below a readable width. */
  minWidth?: number | string;
  showScrollHint?: boolean;
  className?: string;
}) {
  const innerStyle: CSSProperties | undefined = minWidth
    ? { minWidth: typeof minWidth === "number" ? `${minWidth}px` : minWidth }
    : undefined;

  return (
    <div>
      <div
        className={`table-scroll-fade max-h-[70vh] overflow-x-auto overflow-y-auto rounded-panel border border-border-default ${className}`}
      >
        <div style={innerStyle}>{children}</div>
      </div>
      {showScrollHint && <ColumnOverflowHint />}
    </div>
  );
}

/** "This table scrolls sideways" affordance for touch/mobile - the fade edge
 * on TableScrollContainer already hints this visually once scrolled, this
 * adds the same message as text for anyone who doesn't pick up on the fade.
 * Hidden at sm+ where a wide table more often fits, or wide enough that the
 * fade edge alone reads clearly. */
export function ColumnOverflowHint({ className = "" }: { className?: string }) {
  return (
    <div className={`mt-1 text-[11px] text-text-faint sm:hidden ${className}`}>
      ← scroll horizontally for more columns →
    </div>
  );
}

/** Apply to a <tr> to flag a row needing attention (stale/missing data,
 * pending review) - kept very subtle per the design brief ("row warning
 * background only very subtle"). */
export const TABLE_ROW_WARNING_CLASS = "row-warning";

/** Add to a table's first <th>/<td> (both header and every body row) to keep
 * that identifying column in view while the rest of a wide row scrolls
 * underneath it. Opt-in - not every table wants this. */
export const STICKY_FIRST_COLUMN_CLASS = "sticky-col-first";

/** Add to a bespoke (non-`.data-table`) table's <thead> to get the same
 * sticky-header behavior `.data-table` provides by default. */
export const STICKY_TABLE_HEADER_CLASS = "sticky-thead";

/** Outer table chrome (rounded border, horizontal scroll for wide
 * admin/analytics tables, sticky header via the .data-table CSS-layer
 * class in globals.css) - pages keep composing their own <table>/<thead>/
 * <tbody> columns, this only standardizes the wrapper + empty state.
 * `minWidth` (see TableScrollContainer) is optional - pass it for tables
 * dense enough that shrunk columns would stop being readable on tablet. */
export function DataTableShell({
  children,
  isEmpty,
  emptyLabel = "No results found.",
  minWidth,
}: {
  children: ReactNode;
  isEmpty?: boolean;
  emptyLabel?: ReactNode;
  minWidth?: number | string;
}) {
  if (isEmpty) {
    return <EmptyState>{emptyLabel}</EmptyState>;
  }
  return <TableScrollContainer minWidth={minWidth}>{children}</TableScrollContainer>;
}

export interface MobileRecordField {
  label: string;
  value: ReactNode;
}

/** Card-per-row fallback for the rare table that's genuinely unusable even
 * with horizontal scroll (e.g. one with many short-lived free-text columns
 * that don't compress well). Not used by default - horizontal scroll inside
 * TableScrollContainer is the standard mobile treatment (see design brief
 * "do not remove columns globally just to make mobile fit") - reach for this
 * only when that still isn't workable. */
export function MobileRecordList({
  records,
  keyExtractor,
  title,
  actions,
}: {
  records: { id: string | number; fields: MobileRecordField[]; onClick?: () => void }[];
  keyExtractor?: (id: string | number) => string;
  title?: (id: string | number) => ReactNode;
  actions?: (id: string | number) => ReactNode;
}) {
  return (
    <div className="space-y-2">
      {records.map((record) => {
        const Wrapper = record.onClick ? "button" : "div";
        return (
          <Wrapper
            key={keyExtractor ? keyExtractor(record.id) : String(record.id)}
            type={record.onClick ? "button" : undefined}
            onClick={record.onClick}
            className={`vault-card w-full p-3 text-left ${record.onClick ? "hover:border-text-faint" : ""}`}
          >
            {title && <div className="mb-1.5 text-sm font-medium text-text-primary">{title(record.id)}</div>}
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
              {record.fields.map((field) => (
                <div key={field.label} className="min-w-0">
                  <dt className="text-[11px] uppercase tracking-wide text-text-secondary">{field.label}</dt>
                  <dd className="truncate text-text-primary">{field.value}</dd>
                </div>
              ))}
            </dl>
            {actions && <div className="mt-2 flex flex-wrap gap-1.5">{actions(record.id)}</div>}
          </Wrapper>
        );
      })}
    </div>
  );
}
