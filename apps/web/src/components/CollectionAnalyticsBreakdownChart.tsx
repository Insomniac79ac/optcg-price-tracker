"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { EmptyState } from "@/components/StateBlocks";
import type { CollectionAnalyticsBreakdownItem } from "@/lib/api";
import { formatJpy } from "@/lib/format";

/** Value-by-bucket bar chart shared by the collection analytics page's "by
 * set" and "by rarity" breakdowns - split out so app/analytics/collection/
 * page.tsx can dynamically import it (recharts is a sizeable chunk most
 * other pages never need, same rationale as DashboardPortfolioChart). */
export function CollectionAnalyticsBreakdownChart({
  rows,
}: {
  rows: CollectionAnalyticsBreakdownItem[];
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
            formatter={(value) => [formatJpy(Number(value)), "Value"]}
          />
          <Bar dataKey="value_jpy" fill="#38bdf8" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
