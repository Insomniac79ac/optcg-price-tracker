import Link from "next/link";

import { RarityBadge } from "@/components/RarityBadge";
import { EmptyState } from "@/components/StateBlocks";
import type { WishlistAnalyticsTargetItem } from "@/lib/api";
import { cardDisplayName, formatJPY, formatNumber, formatPercent, formatSignedJpy } from "@/lib/format";

export type TargetColumn =
  | "priority"
  | "set_rarity"
  | "quantities"
  | "target_price"
  | "max_price"
  | "current_price"
  | "source"
  | "gap"
  | "target_hit";

const COLUMN_LABELS: Record<TargetColumn, string> = {
  priority: "Priority",
  set_rarity: "Set / Rarity",
  quantities: "Desired / Owned",
  target_price: "Target price",
  max_price: "Max price",
  current_price: "Current price",
  source: "Source",
  gap: "Gap to target",
  target_hit: "Target hit",
};

function renderCell(item: WishlistAnalyticsTargetItem, column: TargetColumn) {
  switch (column) {
    case "priority":
      return <span className="capitalize text-neutral-300">{item.priority}</span>;
    case "set_rarity":
      return (
        <span className="flex items-center gap-1.5">
          <span className="text-neutral-300">{item.set_code}</span>
          <RarityBadge rarity={item.rarity} />
        </span>
      );
    case "quantities":
      return (
        <span className="text-neutral-300">
          {formatNumber(item.desired_quantity)} / {formatNumber(item.owned_quantity)}
        </span>
      );
    case "target_price":
      return formatJPY(item.target_buy_price_jpy);
    case "max_price":
      return formatJPY(item.max_buy_price_jpy);
    case "current_price":
      return formatJPY(item.preferred_current_price_jpy);
    case "source":
      return item.preferred_current_price_source ?? "not available";
    case "gap":
      return item.gap_to_target_jpy === null ? (
        "not available"
      ) : (
        <span className={item.gap_to_target_jpy <= 0 ? "text-emerald-400" : "text-neutral-300"}>
          {formatSignedJpy(item.gap_to_target_jpy)}
          {item.gap_to_target_pct !== null && (
            <span className="ml-1 text-neutral-500">({formatPercent(item.gap_to_target_pct)})</span>
          )}
        </span>
      );
    case "target_hit":
      // Clear but not flashy - a plain colored label, no icon/animation.
      return (
        <span className={item.target_hit ? "text-emerald-400" : "text-neutral-600"}>
          {item.target_hit ? "Hit" : "—"}
        </span>
      );
    default:
      return null;
  }
}

/** Dense per-item table shared by the wishlist analytics page's budget-plan
 * sub-sections and its target-hits section - the columns shown differ per
 * section (see `columns`), but the row shape is identical everywhere. */
export function WishlistAnalyticsTargetTable({
  items,
  columns,
}: {
  items: WishlistAnalyticsTargetItem[];
  columns: TargetColumn[];
}) {
  if (items.length === 0) {
    return <EmptyState variant="inline">No data available.</EmptyState>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-800">
      <table className="w-full min-w-[720px] border-collapse text-xs">
        <thead>
          <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-[11px] uppercase tracking-wide text-neutral-500">
            <th className="px-3 py-2 font-medium">Card</th>
            {columns.map((column) => (
              <th key={column} className="px-3 py-2 font-medium">
                {COLUMN_LABELS[column]}
              </th>
            ))}
            <th className="px-3 py-2 font-medium">Links</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.wishlist_item_id} className="border-b border-neutral-900 last:border-0">
              <td className="px-3 py-2 text-neutral-200">
                <Link href={`/cards/${item.card_id}`} className="text-sky-400 hover:text-sky-300">
                  {item.card_code} · {cardDisplayName(item)}
                </Link>
              </td>
              {columns.map((column) => (
                <td key={column} className="px-3 py-2 text-neutral-300">
                  {renderCell(item, column)}
                </td>
              ))}
              <td className="px-3 py-2">
                <Link href="/wishlist" className="text-sky-400 hover:text-sky-300">
                  Wishlist →
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
