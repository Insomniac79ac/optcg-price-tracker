import { EmptyState } from "@/components/StateBlocks";
import type { WishlistAnalyticsBreakdownItem } from "@/lib/api";
import { formatJPY, formatNumber, formatPercent } from "@/lib/format";

export type WishlistBreakdownColumn =
  | "item_count"
  | "desired_quantity"
  | "target_budget_jpy"
  | "max_budget_jpy"
  | "current_price_jpy"
  | "target_hit_count"
  | "owned_count"
  | "budget_weight_pct";

const COLUMN_LABELS: Record<WishlistBreakdownColumn, string> = {
  item_count: "Items",
  desired_quantity: "Desired qty",
  target_budget_jpy: "Target budget",
  max_budget_jpy: "Max budget",
  current_price_jpy: "Current price",
  target_hit_count: "Target hits",
  owned_count: "Owned",
  budget_weight_pct: "Budget weight %",
};

function renderCell(row: WishlistAnalyticsBreakdownItem, column: WishlistBreakdownColumn) {
  switch (column) {
    case "item_count":
      return formatNumber(row.item_count);
    case "desired_quantity":
      return formatNumber(row.desired_quantity);
    case "target_budget_jpy":
      return formatJPY(row.target_budget_jpy);
    case "max_budget_jpy":
      return formatJPY(row.max_budget_jpy);
    case "current_price_jpy":
      return formatJPY(row.current_price_jpy);
    case "target_hit_count":
      return formatNumber(row.target_hit_count);
    case "owned_count":
      return formatNumber(row.owned_count);
    case "budget_weight_pct":
      return formatPercent(row.budget_weight_pct);
    default:
      return null;
  }
}

/** Dense breakdown table shared by every "by X" section of the wishlist
 * analytics page - same pattern as CollectionAnalyticsBreakdownTable, kept
 * as its own component since the row shape (target/max/current budget
 * fields) differs from the collection analytics breakdown shape. */
export function WishlistAnalyticsBreakdownTable({
  rows,
  firstColumnLabel,
  columns,
}: {
  rows: WishlistAnalyticsBreakdownItem[];
  firstColumnLabel: string;
  columns: WishlistBreakdownColumn[];
}) {
  if (rows.length === 0) {
    return <EmptyState variant="inline">No data available.</EmptyState>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-800">
      <table className="w-full min-w-[520px] border-collapse text-xs">
        <thead>
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
    </div>
  );
}
