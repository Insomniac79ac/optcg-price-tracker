"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { EmptyState } from "@/components/StateBlocks";
import type { WishlistAnalyticsBreakdownItem } from "@/lib/api";
import { formatJpy } from "@/lib/format";

/** Target-budget-by-bucket bar chart for the wishlist analytics page's "by
 * priority"/"by status" breakdowns - split out so the page can dynamically
 * import it (recharts is a sizeable chunk most other pages never need),
 * same pattern as CollectionAnalyticsBreakdownChart. */
export function WishlistAnalyticsBreakdownChart({
  rows,
}: {
  rows: WishlistAnalyticsBreakdownItem[];
}) {
  if (rows.length === 0) {
    return <EmptyState variant="inline">No data available.</EmptyState>;
  }

  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
          <XAxis dataKey="label" stroke="#737373" fontSize={11} tickMargin={8} />
          <YAxis
            tickFormatter={(value: number) => formatJpy(value)}
            stroke="#737373"
            fontSize={11}
            width={70}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#171717",
              border: "1px solid #262626",
              borderRadius: 6,
              fontSize: 12,
            }}
            formatter={(value) => [formatJpy(Number(value)), "Target budget"]}
          />
          <Bar dataKey="target_budget_jpy" fill="#a78bfa" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
