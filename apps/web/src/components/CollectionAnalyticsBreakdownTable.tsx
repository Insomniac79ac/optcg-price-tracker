import { EmptyState } from "@/components/StateBlocks";
import { TableScrollContainer } from "@/components/ui/DataTableShell";
import type { CollectionAnalyticsBreakdownItem } from "@/lib/api";
import { formatNumber, formatPercent, formatSignedJpy, formatJPY } from "@/lib/format";

export type BreakdownColumn = "quantity" | "item_count" | "value" | "weight" | "pnl_pct" | "pnl_jpy";

const COLUMN_LABELS: Record<BreakdownColumn, string> = {
  quantity: "Quantity",
  item_count: "Items",
  value: "Value",
  weight: "Weight %",
  pnl_pct: "P/L %",
  pnl_jpy: "P/L",
};

function pnlTone(value: number | null): string {
  if (value === null || value === 0) return "text-neutral-300";
  return value > 0 ? "text-emerald-400" : "text-rose-400";
}

function renderCell(row: CollectionAnalyticsBreakdownItem, column: BreakdownColumn) {
  switch (column) {
    case "quantity":
      return formatNumber(row.quantity);
    case "item_count":
      return formatNumber(row.item_count);
    case "value":
      return formatJPY(row.value_jpy);
    case "weight":
      return formatPercent(row.portfolio_weight_pct);
    case "pnl_pct":
      return <span className={pnlTone(row.pnl_pct)}>{formatPercent(row.pnl_pct)}</span>;
    case "pnl_jpy":
      return <span className={pnlTone(row.pnl_jpy)}>{formatSignedJpy(row.pnl_jpy)}</span>;
    default:
      return null;
  }
}

/** Dense breakdown table shared by every "by X" section of the collection
 * analytics page - the columns shown differ per section (see `columns`),
 * but the row shape (key/label/aggregates) is identical across all of them. */
export function CollectionAnalyticsBreakdownTable({
  rows,
  firstColumnLabel,
  columns,
}: {
  rows: CollectionAnalyticsBreakdownItem[];
  firstColumnLabel: string;
  columns: BreakdownColumn[];
}) {
  if (rows.length === 0) {
    return <EmptyState variant="inline">No data available.</EmptyState>;
  }

  return (
    <TableScrollContainer showScrollHint={false}>
      <table className="w-full min-w-[420px] border-collapse text-xs">
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
