"use client";

import {
  CartesianGrid,
  Legend,
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

interface SeriesDef {
  key: string;
  label: string;
  source: string;
  priceType: string;
  color: string;
}

const SERIES: SeriesDef[] = [
  { key: "yuyutei_sell", label: "Yuyu-Tei sell", source: "yuyutei", priceType: "sell", color: "#38bdf8" },
  { key: "yuyutei_buy", label: "Yuyu-Tei buy", source: "yuyutei", priceType: "buy", color: "#a78bfa" },
  { key: "snkrdunk_floor", label: "SNKRDUNK floor", source: "snkrdunk", priceType: "floor", color: "#34d399" },
];

export function PriceChart({ observations }: PriceChartProps) {
  if (observations.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center rounded-lg border border-neutral-800 bg-neutral-900 text-sm text-neutral-500">
        No price observations yet
      </div>
    );
  }

  // Any source/price_type combos beyond the three known lines still get
  // plotted, so the chart never silently drops data.
  const seriesDefs = [...SERIES];
  for (const obs of observations) {
    const key = `${obs.source}_${obs.price_type}`;
    if (!seriesDefs.some((s) => s.key === key)) {
      seriesDefs.push({
        key,
        label: `${obs.source} ${obs.price_type}`,
        source: obs.source,
        priceType: obs.price_type,
        color: "#f472b6",
      });
    }
  }

  const dates = Array.from(
    new Set(observations.map((obs) => obs.observed_at)),
  ).sort((a, b) => new Date(a).getTime() - new Date(b).getTime());

  const data = dates.map((date) => {
    const row: Record<string, string | number> = { observed_at: date };
    for (const series of seriesDefs) {
      const match = observations.find(
        (obs) =>
          obs.observed_at === date &&
          obs.source === series.source &&
          obs.price_type === series.priceType,
      );
      if (match) row[series.key] = match.price_jpy;
    }
    return row;
  });

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
            formatter={(value, name) => [formatJpy(Number(value)), String(name)]}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {seriesDefs.map((series) => (
            <Line
              key={series.key}
              type="monotone"
              dataKey={series.key}
              name={series.label}
              stroke={series.color}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
