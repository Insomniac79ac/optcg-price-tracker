import { marketNumber, type MarketValue } from "./marketValue";

export interface MarketComparisonPoint {
  date: string;
  timestamp: number;
  values: Record<number, number>;
}

/** Validate the actual daily window before sharing an axis. No interpolation,
 * date shifts, rebasing, or return calculation: values are server percentages. */
export function marketComparisonRows(series: MarketValue[]): MarketComparisonPoint[] | null {
  if (!series.length) return null;
  const first = series[0];
  const dates = first.series.map((point) => point.date);
  if (dates.length !== 8) return null;
  for (const data of series) {
    if (data.scope_kind !== "release" || data.release_product_id === null ||
      data.movement.window !== "7d" || !data.movement.available ||
      data.movement.from_date !== dates[0] || data.movement.to_date !== dates[7] ||
      data.as_of !== dates[7] || data.methodology_version !== first.methodology_version || data.series.length !== 8) return null;
    for (let index = 0; index < data.series.length; index++) {
      const point = data.series[index];
      const timestamp = Date.parse(`${point.date}T00:00:00Z`);
      if (!Number.isFinite(timestamp) || new Date(timestamp).toISOString().slice(0, 10) !== point.date ||
        point.date !== dates[index] || marketNumber(point.performance_pct) === null ||
        (index > 0 && timestamp - Date.parse(`${dates[index - 1]}T00:00:00Z`) !== 86_400_000)) return null;
    }
  }
  return dates.map((date, index) => ({
    date,
    timestamp: Date.parse(`${date}T00:00:00Z`),
    values: Object.fromEntries(series.map((data) => [data.release_product_id!, marketNumber(data.series[index].performance_pct)!])),
  }));
}

export function releaseMovementReason(reason: string): string {
  if (["insufficient_comparable_prints", "insufficient_physical_coverage", "insufficient_comparable_value_coverage", "non_positive_comparable_value"].includes(reason)) return "Coverage in progress";
  if (reason === "insufficient_window_continuity") return "Not enough history";
  return "Movement unavailable";
}
