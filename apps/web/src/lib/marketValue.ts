import { apiGet } from "./api";
import type { PrintDisplayImage } from "./prints";

export const MARKET_VALUE_WINDOWS = ["7d", "30d", "all"] as const;
export type MarketValueWindow = (typeof MARKET_VALUE_WINDOWS)[number];
export type MarketValueMode = "performance" | "value";

// Market Value percentages are Decimal strings; conversion is for display
// geometry only. The browser never chains returns or rebases performance.
export interface MarketValueTracked {
  value_jpy: number | null;
  priced_print_count: number;
  total_physical_print_count: number;
  physical_coverage_pct: string | null;
  is_partial: boolean;
}

export interface MarketValueMovementSummary {
  available: boolean;
  pct: string | null;
  reason: string;
}

export interface MarketValuePoint {
  date: string;
  tracked_value_jpy: number | null;
  priced_print_count: number;
  total_physical_print_count: number;
  performance_pct: string | null;
  step_publication_eligible: boolean | null;
  publication_reason: string;
}

export interface MarketValue {
  scope_kind: "overall" | "release";
  release_product_id: number | null;
  release_code: string | null;
  release_name: string | null;
  methodology_version: number;
  as_of: string;
  tracked_value: MarketValueTracked;
  movement: MarketValueMovementSummary & {
    window: MarketValueWindow;
    from_date: string;
    to_date: string;
    fraction: string | null;
  };
  series: MarketValuePoint[];
}

export interface MarketValueRelease {
  release_product_id: number;
  release_code: string;
  release_name: string;
  methodology_version: number;
  as_of: string;
  tracked_value: MarketValueTracked;
  seven_day: MarketValueMovementSummary;
  thirty_day: MarketValueMovementSummary;
}

export interface MarketValueReleases {
  items: MarketValueRelease[];
  ordering_basis: "released_on_desc_then_deterministic_fallback";
}

export function fetchMarketValue(releaseProductId: number | null, window: MarketValueWindow) {
  return apiGet<MarketValue>("/analytics/market-value", {
    params: { release_product_id: releaseProductId, window },
  });
}

export function fetchMarketValueReleases() {
  return apiGet<MarketValueReleases>("/analytics/market-value/releases");
}

export type MarketValueMoverOrder = "gainers" | "losers" | "impact";

interface MarketValueRankingScope {
  scope_kind: "overall" | "release";
  release_product_id: number | null;
  release_code: string | null;
  release_name: string | null;
  methodology_version: number;
}

export interface MarketValuePrint {
  card_print_id: number;
  canonical_card_id: number;
  card_code: string;
  name: string;
  rarity: string | null;
  treatment: string | null;
  official_asset_variant: string;
  release_product_id: number;
  release_code: string | null;
  release_name: string;
  display_image: PrintDisplayImage | null;
}

export interface MarketValueMover extends MarketValuePrint {
  prior_value_jpy: number;
  current_value_jpy: number;
  delta_jpy: number;
  // Decimal strings from the server. Format only; never recompute or rank.
  move_fraction: string;
  move_pct: string;
  percentage_point_contribution: string;
  direction: "up" | "down" | "flat";
  rank: number;
}

export interface MarketValueMovers extends MarketValueRankingScope {
  available: boolean;
  reason: "publishable" | "no_published_daily_step";
  scope_as_of: string;
  step_date: string | null;
  prior_date: string | null;
  panel: {
    comparable_print_count: number | null;
    prior_value_jpy: number | null;
    current_value_jpy: number | null;
    basket_delta_jpy: number | null;
    basket_move_pct: string | null;
  };
  order: MarketValueMoverOrder;
  total_ranked: number;
  returned: number;
  truncated: boolean;
  movers: MarketValueMover[];
}

export interface MarketValueValuablePrint extends MarketValuePrint {
  value_jpy: number;
  calculated_at: string;
}

export interface MarketValueMostValuable extends MarketValueRankingScope {
  as_of: string;
  calculated_at: string | null;
  total_eligible: number;
  limit: number;
  offset: number;
  items: MarketValueValuablePrint[];
}

export function fetchMarketValueMovers(releaseProductId: number | null, order: MarketValueMoverOrder) {
  return apiGet<MarketValueMovers>("/analytics/market-value/movers", {
    params: { release_product_id: releaseProductId, order, limit: 5 },
  });
}

export function fetchMarketValueMostValuable(releaseProductId: number | null) {
  return apiGet<MarketValueMostValuable>("/analytics/market-value/most-valuable", {
    params: { release_product_id: releaseProductId, limit: 6 },
  });
}

export function marketSignedJpy(value: number): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${marketJpy(Math.abs(value))}`;
}

export function marketPercentagePoints(value: string): string {
  return `${marketPercent(value).replace(/%$/, "")} percentage points`;
}

/** null selects Overall; malformed IDs must never silently select Overall. */
export function parseMarketRelease(raw: string | null): number | null | "invalid" {
  if (raw === null) return null;
  if (!/^[1-9]\d*$/.test(raw)) return "invalid";
  const id = Number(raw);
  return Number.isSafeInteger(id) ? id : "invalid";
}

export function marketScopeUrl(releaseProductId: number | null): string {
  return releaseProductId === null
    ? "/analytics"
    : `/analytics?release_product_id=${releaseProductId}`;
}

export function marketWindowLabel(window: MarketValueWindow): string {
  return window.toUpperCase();
}

export function marketNumber(value: string | number | null): number | null {
  if (value === null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function marketPercent(value: string | number | null, signed = true): string {
  const number = marketNumber(value);
  if (number === null) return "Unavailable";
  const rounded = Number(number.toFixed(2));
  return `${signed && rounded > 0 ? "+" : rounded < 0 ? "−" : ""}${Math.abs(rounded).toFixed(2)}%`;
}

export function marketJpy(value: number | null): string {
  return value === null ? "Not yet priced" : `¥${value.toLocaleString("en-US")}`;
}

export function marketDate(value: string, year = false): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", ...(year ? { year: "numeric" } : {}), timeZone: "UTC",
  }).format(new Date(`${value}T00:00:00Z`));
}

export function movementUnavailable(data: MarketValue) {
  const coverage = new Set([
    "insufficient_comparable_prints", "insufficient_physical_coverage",
    "insufficient_comparable_value_coverage", "non_positive_comparable_value",
  ]).has(data.movement.reason);
  return {
    title: coverage ? "Price coverage in progress" : "Price movement unavailable",
    detail: coverage
      ? "More comparable card variants are needed to show price movement for this view."
      : `There isn’t a continuous, comparable price history for ${data.movement.window === "all" ? "the full archive" : `this ${marketWindowLabel(data.movement.window)} window`} yet.`,
  };
}

export interface MarketChartPoint {
  date: string;
  timestamp: number;
  value: number | null;
  priced: number | null;
  physical: number | null;
}

/** Preserve server nulls and put a gap between non-adjacent dates. Gap rows
 * have no valuation; they only prevent the chart from joining missing days. */
export function marketChartPoints(series: MarketValuePoint[], mode: MarketValueMode): MarketChartPoint[] {
  const rows: MarketChartPoint[] = [];
  for (const point of series) {
    const timestamp = Date.parse(`${point.date}T00:00:00Z`);
    const previous = rows.at(-1);
    if (previous && timestamp - previous.timestamp > 86_400_000) {
      rows.push({ date: "", timestamp: previous.timestamp + 86_400_000, value: null, priced: null, physical: null });
    }
    rows.push({
      date: point.date,
      timestamp,
      value: mode === "performance" ? marketNumber(point.performance_pct) : point.tracked_value_jpy,
      priced: point.priced_print_count,
      physical: point.total_physical_print_count,
    });
  }
  return rows;
}
