import type { ReactNode } from "react";

import { EmptyState } from "@/components/StateBlocks";

/** Outer table chrome (rounded border, horizontal scroll for wide
 * admin/analytics tables, sticky header via the .data-table CSS-layer
 * class in globals.css) - pages keep composing their own <table>/<thead>/
 * <tbody> columns, this only standardizes the wrapper + empty state. */
export function DataTableShell({
  children,
  isEmpty,
  emptyLabel = "No results found.",
}: {
  children: ReactNode;
  isEmpty?: boolean;
  emptyLabel?: ReactNode;
}) {
  if (isEmpty) {
    return <EmptyState>{emptyLabel}</EmptyState>;
  }
  return (
    <div className="max-h-[70vh] overflow-x-auto overflow-y-auto rounded-panel border border-border-default">
      {children}
    </div>
  );
}

/** Apply to a <tr> to flag a row needing attention (stale/missing data,
 * pending review) - kept very subtle per the design brief ("row warning
 * background only very subtle"). */
export const TABLE_ROW_WARNING_CLASS = "row-warning";
