"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { EmptyState } from "@/components/StateBlocks";
import type { PortfolioChartWidget } from "@/lib/api";
import { formatDate, formatDateTime, formatJpy } from "@/lib/format";

/** The dashboard's "Portfolio value over time" widget - split out from
 * app/dashboard/page.tsx so it can be dynamically imported there (recharts
 * is a sizeable chunk that most other pages never need). */
export function DashboardPortfolioChart({
  widget,
  showRawMarketValue,
  showGradedAdjustedValue,
}: {
  widget: PortfolioChartWidget;
  showRawMarketValue: boolean;
  showGradedAdjustedValue: boolean;
}) {
  return (
    <>
      <div className="mb-2 text-xs text-neutral-500">Timeframe: {widget.timeframe}</div>
      {widget.points.length === 0 ? (
        <EmptyState variant="inline">No valuation history yet</EmptyState>
      ) : (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={widget.points} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
              <XAxis
                dataKey="created_at"
                tickFormatter={(value: string) => formatDate(value)}
                stroke="#737373"
                fontSize={11}
                tickMargin={8}
                minTickGap={24}
              />
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
                labelFormatter={(value) => formatDateTime(String(value))}
                formatter={(value, name) => [formatJpy(Number(value)), String(name)]}
              />
              {showRawMarketValue && (
                <Line
                  type="monotone"
                  dataKey="market_floor_value_jpy"
                  name="Market floor"
                  stroke="#34d399"
                  strokeWidth={2}
                  dot={widget.points.length === 1}
                  connectNulls
                />
              )}
              {showGradedAdjustedValue && (
                <Line
                  type="monotone"
                  dataKey="graded_adjusted_value_jpy"
                  name="Graded-adjusted"
                  stroke="#fb7185"
                  strokeWidth={2}
                  dot={widget.points.length === 1}
                  connectNulls
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </>
  );
}
