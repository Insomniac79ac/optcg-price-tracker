import { EmptyState } from "@/components/StateBlocks";
import { TableScrollContainer } from "@/components/ui/DataTableShell";
import type { GradingAnalyticsBreakdownItem } from "@/lib/api";
import { formatJPY, formatNumber, formatPercent } from "@/lib/format";

export type GradingBreakdownColumn =
  | "submission_count"
  | "received_count"
  | "active_count"
  | "total_cost_jpy"
  | "graded_value_jpy"
  | "roi_jpy"
  | "roi_pct";

const COLUMN_LABELS: Record<GradingBreakdownColumn, string> = {
  submission_count: "Submissions",
  received_count: "Received",
  active_count: "Active",
  total_cost_jpy: "Total cost",
  graded_value_jpy: "Graded value",
  roi_jpy: "ROI",
  roi_pct: "ROI %",
};

function renderCell(row: GradingAnalyticsBreakdownItem, column: GradingBreakdownColumn) {
  switch (column) {
    case "submission_count":
      return formatNumber(row.submission_count);
    case "received_count":
      return formatNumber(row.received_count);
    case "active_count":
      return formatNumber(row.active_count);
    case "total_cost_jpy":
      return formatJPY(row.total_cost_jpy);
    case "graded_value_jpy":
      return formatJPY(row.graded_value_jpy);
    case "roi_jpy":
      return (
        <span className={row.roi_jpy >= 0 ? "text-emerald-400" : "text-rose-400"}>
          {formatJPY(row.roi_jpy)}
        </span>
      );
    case "roi_pct":
      return formatPercent(row.roi_pct);
    default:
      return null;
  }
}

/** Dense breakdown table shared by every "by X" section of the grading
 * analytics page - same pattern as WishlistAnalyticsBreakdownTable /
 * SellDecisionCandidateTable's breakdown-style tables. */
export function GradingAnalyticsBreakdownTable({
  rows,
  firstColumnLabel,
  columns,
}: {
  rows: GradingAnalyticsBreakdownItem[];
  firstColumnLabel: string;
  columns: GradingBreakdownColumn[];
}) {
  if (rows.length === 0) {
    return <EmptyState variant="inline">No data available.</EmptyState>;
  }

  return (
    <TableScrollContainer showScrollHint={false}>
      <table className="w-full min-w-[520px] border-collapse text-xs">
        <thead className="sticky-thead">
          <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
            <th className="px-3 py-2 font-medium">{firstColumnLabel}</th>
            {columns.map((column) => (
              <th key={column} className="px-3 py-2 text-right font-medium">
                {COLUMN_LABELS[column]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-b border-neutral-900 last:border-0">
              <td className="px-3 py-2 text-neutral-200">{row.label}</td>
              {columns.map((column) => (
                <td key={column} className="px-3 py-2 text-right text-neutral-300">
                  {renderCell(row, column)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </TableScrollContainer>
  );
}
