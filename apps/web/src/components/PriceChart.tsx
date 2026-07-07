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

import type { PriceObservation } from "@/lib/api";
import { formatDate, formatJpy } from "@/lib/format";

interface PriceChartProps {
  observations: PriceObservation[];
}

interface ChartPoint {
  observed_at: string;
  price_jpy: number;
}

export function PriceChart({ observations }: PriceChartProps) {
  if (observations.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center rounded-lg border border-neutral-800 bg-neutral-900 text-sm text-neutral-500">
        No price observations yet
      </div>
    );
  }

  const data: ChartPoint[] = observations
    .slice()
    .sort(
      (a, b) =>
        new Date(a.observed_at).getTime() - new Date(b.observed_at).getTime(),
    )
    .map((obs) => ({
      observed_at: obs.observed_at,
      price_jpy: obs.price_jpy,
    }));

  return (
    <div className="h-64 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
          <XAxis
            dataKey="observed_at"
            tickFormatter={(value: string) => formatDate(value)}
            stroke="#737373"
            fontSize={12}
            tickMargin={8}
          />
          <YAxis
            tickFormatter={(value: number) => formatJpy(value)}
            stroke="#737373"
            fontSize={12}
            width={80}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#171717",
              border: "1px solid #262626",
              borderRadius: 6,
              fontSize: 12,
            }}
            labelStyle={{ color: "#a3a3a3" }}
            labelFormatter={(value) => formatDate(String(value))}
            formatter={(value) => [formatJpy(Number(value)), "Price"]}
          />
          <Line
            type="monotone"
            dataKey="price_jpy"
            stroke="#38bdf8"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
