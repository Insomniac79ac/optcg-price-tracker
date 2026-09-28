"use client";

import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PUBLIC_CHART_PALETTE } from "@/lib/chartPalette";
import { marketDate, marketPercent, type MarketValue } from "@/lib/marketValue";
import { marketComparisonRows, type MarketComparisonPoint } from "@/lib/marketValueComparison";
import styles from "./MarketValueReleases.module.css";

// Reuse the public multi-series chart palette; colour never signifies a winner.
export const COMPARISON_COLORS = [PUBLIC_CHART_PALETTE.gold, PUBLIC_CHART_PALETTE.teal, PUBLIC_CHART_PALETTE.parchment, PUBLIC_CHART_PALETTE.blue];
const DASHES = [undefined, "7 4", "2 4", "9 3 2 3"];
export interface ComparisonLine {
  id: number;
  code: string;
  label: string;
  slot: number;
  data: MarketValue;
}

export function MarketValueComparisonChart({ lines }: { lines: ComparisonLine[] }) {
  const rows = marketComparisonRows(lines.map((line) => line.data));
  if (!rows) return <div className={styles.empty} role="status"><h3>Comparison unavailable</h3><p>These releases do not share a complete 7D period. Try a different selection.</p></div>;
  return <div className={styles.plot} role="region" aria-label="Release comparison chart" data-testid="comparison-chart">
    <ResponsiveContainer width="100%" height="100%" minWidth={0}>
      <LineChart data={rows} margin={{ top: 16, right: 14, bottom: 10, left: 0 }} accessibilityLayer>
        <CartesianGrid vertical={false} stroke="var(--border-muted)" strokeDasharray="3 6" />
        <XAxis dataKey="timestamp" type="number" scale="time" domain={["dataMin", "dataMax"]} tickLine={false} axisLine={false} minTickGap={40} tickMargin={12} tick={{ fill: "var(--text-muted)", fontSize: 11 }} tickFormatter={(value: number) => marketDate(new Date(value).toISOString().slice(0, 10))} />
        <YAxis width={48} tickLine={false} axisLine={false} tickCount={5} tickMargin={8} tick={{ fill: "var(--text-muted)", fontSize: 11 }} domain={[(min: number) => Math.min(0, min), (max: number) => Math.max(0, max)]} tickFormatter={(value: number) => `${Number(value.toFixed(1))}%`} />
        <ReferenceLine y={0} stroke="var(--text-faint)" strokeDasharray="3 6" label={{ value: "0%", position: "insideTopLeft", fill: "var(--text-muted)", fontSize: 10 }} />
        <Tooltip content={<MarketValueComparisonTooltip lines={lines} />} cursor={{ stroke: "var(--text-muted)", strokeDasharray: "3 4" }} />
        {lines.map((line) => <Line key={line.id} dataKey={`values.${line.id}`} name={line.code} type="linear" stroke={COMPARISON_COLORS[line.slot]} strokeDasharray={DASHES[line.slot]} strokeWidth={2.5} dot={false} activeDot={{ r: 4 }} connectNulls={false} isAnimationActive={false} />)}
      </LineChart>
    </ResponsiveContainer>
  </div>;
}

export function MarketValueComparisonTooltip({ active, payload, lines }: {
  active?: boolean;
  payload?: { payload?: MarketComparisonPoint }[];
  lines: ComparisonLine[];
}) {
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  return <div className={styles.tooltip}>
    <p>{marketDate(row.date, true)}</p>
    {lines.map((line) => <div key={line.id} title={line.label}><span style={{ color: COMPARISON_COLORS[line.slot] }}>{line.code}</span><strong>{marketPercent(row.values[line.id])}</strong></div>)}
  </div>;
}
