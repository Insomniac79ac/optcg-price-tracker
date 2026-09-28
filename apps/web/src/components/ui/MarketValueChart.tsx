"use client";

import { useId } from "react";
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { marketChartPoints, marketDate, marketJpy, marketPercent, type MarketChartPoint, type MarketValueMode, type MarketValuePoint } from "@/lib/marketValue";
import styles from "./MarketValueHero.module.css";

export function MarketValueChart({ series, mode }: { series: MarketValuePoint[]; mode: MarketValueMode }) {
  const gradient = useId().replace(/:/g, "");
  const rows = marketChartPoints(series, mode);
  const color = mode === "performance" ? "var(--accent-gold)" : "var(--accent-teal-hover)";
  const valid = rows.filter((row) => row.value !== null);
  if (!valid.length) {
    return <div className={styles.chartEmpty}><p>No priced history in this window yet.</p></div>;
  }
  return (
    <div className={styles.plot} role="region" aria-label={`${mode === "performance" ? "Performance" : "Tracked value"} chart`} data-testid="market-value-chart">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <AreaChart data={rows} margin={{ top: 20, right: 12, bottom: 8, left: 0 }} accessibilityLayer>
          <defs>
            <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.18} />
              <stop offset="100%" stopColor={color} stopOpacity={0.01} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--border-muted)" strokeDasharray="3 6" />
          <XAxis dataKey="timestamp" type="number" domain={["dataMin", "dataMax"]} scale="time" tickLine={false} axisLine={false} minTickGap={40} tickMargin={12} tick={{ fill: "var(--text-muted)", fontSize: 11 }} tickFormatter={(value: number) => marketDate(new Date(value).toISOString().slice(0, 10))} />
          <YAxis width={60} tickLine={false} axisLine={false} tickCount={5} tickMargin={12} tick={{ fill: "var(--text-muted)", fontSize: 11 }} domain={mode === "performance" ? ["auto", "auto"] : [0, "auto"]} tickFormatter={(value: number) => mode === "performance" ? `${value}%` : `¥${new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value)}`} />
          {mode === "performance" && <ReferenceLine y={0} stroke="var(--text-faint)" strokeDasharray="3 6" />}
          <Tooltip content={<MarketValueChartTooltip mode={mode} />} cursor={{ stroke: "var(--text-muted)", strokeDasharray: "3 4" }} />
          <Area type="linear" dataKey="value" name={mode === "performance" ? "Performance" : "Tracked value"} stroke={color} strokeWidth={2.5} fill={`url(#${gradient})`} connectNulls={false} isAnimationActive={false} dot={valid.length === 1 ? { r: 3 } : false} activeDot={{ r: 4, stroke: "var(--bg-page)", strokeWidth: 2 }} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function MarketValueChartTooltip({ active, payload, mode }: {
  active?: boolean;
  payload?: { payload?: MarketChartPoint }[];
  mode: MarketValueMode;
}) {
  const row = payload?.[0]?.payload;
  if (!active || !row?.date || row.value === null) return null;
  return (
    <div className={styles.tooltip}>
      <p>{marketDate(row.date, true)}</p>
      <strong>{mode === "performance" ? marketPercent(row.value) : marketJpy(row.value)}</strong>
      {mode === "value" && row.priced !== null && row.physical !== null && <p>{row.priced.toLocaleString("en-US")} / {row.physical.toLocaleString("en-US")} printings priced</p>}
    </div>
  );
}
