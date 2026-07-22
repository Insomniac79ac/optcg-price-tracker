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

import type { PortfolioValuationSnapshot } from "@/lib/api";
import { formatDateTime, formatJpy } from "@/lib/format";

export type HistoryTimeframe = "7" | "30" | "90" | "all";

export const HISTORY_TIMEFRAME_OPTIONS: {
  value: HistoryTimeframe;
  label: string;
}[] = [
  { value: "7", label: "7d" },
  { value: "30", label: "30d" },
  { value: "90", label: "90d" },
  { value: "all", label: "All" },
];

interface SeriesDef {
  key: keyof PortfolioValuationSnapshot;
  label: string;
  color: string;
}

const SERIES: SeriesDef[] = [
  { key: "total_cost_basis_jpy", label: "Total cost basis", color: "#f59e0b" },
  { key: "retail_value_jpy", label: "Yuyu-Tei retail value", color: "#38bdf8" },
  {
    key: "liquidation_value_jpy",
    label: "Yuyu-Tei liquidation value",
    color: "#a78bfa",
  },
  {
    key: "market_floor_value_jpy",
    label: "SNKRDUNK market floor value",
    color: "#34d399",
  },
  {
    key: "graded_adjusted_value_jpy",
    label: "Graded-adjusted value",
    color: "#fb7185",
  },
];

interface PortfolioValuationHistoryChartProps {
  snapshots: PortfolioValuationSnapshot[];
  status: "loading" | "error" | "ready";
  timeframe: HistoryTimeframe;
  onTimeframeChange: (value: HistoryTimeframe) => void;
}

export function PortfolioValuationHistoryChart({
  snapshots,
  status,
  timeframe,
  onTimeframeChange,
}: PortfolioValuationHistoryChartProps) {
  return (
    <section className="mb-6 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-neutral-200">
          Portfolio value over time
        </h2>
        <div className="flex gap-1">
          {HISTORY_TIMEFRAME_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => onTimeframeChange(opt.value)}
              className={`rounded-control px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                timeframe === opt.value
                  ? "bg-accent-gold text-black/80 ring-accent-gold"
                  : "bg-bg-surface text-text-muted ring-border-default hover:text-text-primary"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {status === "loading" && (
        <div className="flex h-64 items-center justify-center text-sm text-neutral-500">
          Loading valuation history…
        </div>
      )}

      {status === "error" && (
        <div className="flex h-64 items-center justify-center text-sm text-rose-300">
          Failed to load valuation history.
        </div>
      )}

      {status === "ready" && snapshots.length === 0 && (
        <div className="flex h-64 items-center justify-center text-sm text-neutral-500">
          No valuation history yet
        </div>
      )}

      {status === "ready" && snapshots.length > 0 && (
        <>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={snapshots}
                margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
                <XAxis
                  dataKey="created_at"
                  tickFormatter={(value: string) => formatDateTime(value)}
                  stroke="#737373"
                  fontSize={12}
                  tickMargin={8}
                  minTickGap={24}
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
                  labelFormatter={(value) => formatDateTime(String(value))}
                  formatter={(value, name) => [
                    formatJpy(Number(value)),
                    String(name),
                  ]}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {SERIES.map((series) => (
                  <Line
                    key={series.key}
                    type="monotone"
                    dataKey={series.key}
                    name={series.label}
                    stroke={series.color}
                    strokeWidth={2}
                    dot={snapshots.length === 1}
                    activeDot={{ r: 4 }}
                    connectNulls
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
          {snapshots.length === 1 && (
            <p className="mt-2 text-xs text-neutral-500">
              More history will appear as scheduled refreshes run.
            </p>
          )}
        </>
      )}
    </section>
  );
}
