/** The v1 collection API shapes (services/api/app/accounts/schemas.py) and the
 * pure helpers /collection renders them with (Collector v1 S7, PLAN §C, §E2).
 *
 * Nothing here computes a price, a total or a change: every number on the
 * page is the API's. These helpers only choose words for what the API says,
 * including why a number is missing. */

export const COLLECTION_WINDOWS = ["7d", "30d", "all"] as const;
export type CollectionWindow = (typeof COLLECTION_WINDOWS)[number];

export const WINDOW_LABEL: Record<CollectionWindow, string> = { "7d": "7D", "30d": "30D", all: "ALL" };

export function parseCollectionWindow(raw: string | string[] | undefined): CollectionWindow {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return (COLLECTION_WINDOWS as readonly string[]).includes(value ?? "") ? (value as CollectionWindow) : "7d";
}

export interface PrintSummary {
  card_print_id: number;
  card_code: string | null;
  name_en: string | null;
  name_jp: string | null;
  treatment: string | null;
  official_asset_variant: string | null;
  release_product_id: number | null;
  release_code: string | null;
  release_name: string | null;
}

export interface CollectionEntry {
  id: number;
  card_print_id: number | null;
  resolution: "exact" | "unresolved";
  quantity: number;
  paid_jpy_per_card: number | null;
  acquired_on: string | null;
  note: string | null;
  legacy_card_id: number | null;
  print: PrintSummary | null;
  value_status: "priced" | "no_price" | "unresolved";
  value_per_card_jpy: number | null;
  value_jpy: number | null;
}

export interface Coverage {
  value_jpy: number | null;
  priced_cards: number;
  total_cards: number;
  priced_entries: number;
  total_entries: number;
  unresolved_entries: number;
  coverage_pct: string | null;
}

export interface CollectionResponse {
  as_of: string | null;
  summary: Coverage;
  entries: CollectionEntry[];
}

export interface Mover {
  card_print_id: number;
  units: number;
  prior_value_per_card_jpy: number;
  current_value_per_card_jpy: number;
  delta_jpy: number;
  change_pct: string | null;
  contribution_pct_points: string | null;
}

export interface Step {
  available: boolean;
  reason: string | null;
  from_date: string | null;
  to_date: string | null;
  missing_dates: string[];
  comparable_cards: number;
  change_jpy: number | null;
  change_pct: string | null;
}

export interface ReleaseShare {
  release_product_id: number | null;
  release_code: string | null;
  release_name: string | null;
  value_jpy: number | null;
  priced_cards: number;
  total_cards: number;
  share_pct: string | null;
  change: Step;
}

export interface PaidSummary {
  cards_with_paid: number;
  cards_compared: number;
  total_cards: number;
  paid_jpy: number | null;
  priced_today_jpy: number | null;
  change_pct: string | null;
}

export interface RecordedChange {
  window: string;
  available: boolean;
  reason: string | null;
  from_date: string | null;
  to_date: string | null;
  change_pct: string | null;
  missing_dates: string[];
}

export interface HistoryPoint {
  date: string;
  value_jpy: number | null;
}

export interface CollectionValue {
  as_of: string | null;
  window: CollectionWindow;
  summary: Coverage;
  movers: Step & { up: Mover[]; down: Mover[] };
  /** Every comparable version's change over the window; absent from an
   * older API, empty when the window is unavailable. */
  cards?: Mover[];
  by_release: ReleaseShare[];
  paid: PaidSummary;
  history: { change: RecordedChange; points: HistoryPoint[] };
  preview: { label: string; change: RecordedChange; points: HistoryPoint[] };
}

const REASONS: Record<string, string> = {
  not_enough_price_history: "Not enough price history yet",
  not_enough_history: "Not enough history yet",
  no_prices_yet: "No prices yet",
  no_cards: "No cards yet",
  no_comparable_cards: "No priced cards held across the whole window",
  insufficient_comparable_value_coverage: "Too few of your cards are priced at both ends",
  prior_day_missing: "A day's prices are missing in this window",
};

const SHORT_DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

/** "14 Oct", from an ISO date (YYYY-MM-DD), read as a calendar day in UTC so
 * the server's timezone can never move it. */
export function shortDate(iso: string | null | undefined): string | null {
  if (!iso || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return null;
  const date = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? null : SHORT_DATE.format(date);
}

/** Why a window has no change, in words. Never "0%". */
export function unavailableReason(change: { reason: string | null; missing_dates?: string[] } | null | undefined): string {
  if (!change) return "Not available right now";
  if (change.reason === "prices_missing" || change.reason === "history_missing") {
    const days = (change.missing_dates ?? []).map(shortDate).filter(Boolean);
    if (days.length === 1) return `Prices missing on ${days[0]}`;
    if (days.length > 1) return `Prices missing on ${days.length} days`;
    return "Prices missing for part of this window";
  }
  return (change.reason && REASONS[change.reason]) || "Not available for this window";
}

/** "+2.40%" / "−3.10%" from the API's decimal string; null when the API gave
 * none. A real minus sign, so the sign never reads as a hyphen. */
export function signedPct(raw: string | null | undefined): string | null {
  if (raw === null || raw === undefined || raw === "") return null;
  const value = Number(raw);
  if (!Number.isFinite(value)) return null;
  const abs = Math.abs(value).toFixed(value !== 0 && Math.abs(value) < 0.1 ? 2 : 1);
  if (Number(abs) === 0) return "0.0%";
  return `${value > 0 ? "+" : "−"}${abs}%`;
}

export function direction(raw: string | number | null | undefined): "up" | "down" | "flat" {
  const value = typeof raw === "number" ? raw : Number(raw);
  if (!Number.isFinite(value) || value === 0) return "flat";
  return value > 0 ? "up" : "down";
}

const YEN = new Intl.NumberFormat("ja-JP", { style: "currency", currency: "JPY", maximumFractionDigits: 0 });

export function yen(value: number): string {
  return YEN.format(value);
}

export function signedYen(value: number): string {
  if (value === 0) return YEN.format(0);
  return `${value > 0 ? "+" : "−"}${YEN.format(Math.abs(value))}`;
}

/** "Priced: 11 of 14 cards (79%)". The API's own percentage, rounded for
 * reading; the counts are the API's. */
export function coverageLine(summary: Coverage): string {
  const cards = summary.total_cards === 1 ? "card" : "cards";
  const pct = summary.coverage_pct !== null ? Number(summary.coverage_pct) : null;
  const tail = pct !== null && Number.isFinite(pct) ? ` (${Math.round(pct)}%)` : "";
  return `Priced: ${summary.priced_cards} of ${summary.total_cards} ${cards}${tail}`;
}

export function cardName(print: Pick<PrintSummary, "name_en" | "name_jp"> | null): string {
  return print?.name_en || print?.name_jp || "Unknown card";
}

/** The per-card change for one version over the selected window: the API's
 * figure when the version was comparable at both ends, otherwise why not. */
export type TileChange = { kind: "change"; pct: string; direction: "up" | "down" | "flat" } | { kind: "none"; reason: string };

export function tileChange(value: CollectionValue | null, entry: CollectionEntry): TileChange {
  if (!value) return { kind: "none", reason: "Not available right now" };
  if (entry.value_status !== "priced" || entry.card_print_id === null) return { kind: "none", reason: "No price yet" };
  if (!value.movers.available) return { kind: "none", reason: unavailableReason(value.movers) };
  const card = value.cards?.find((item) => item.card_print_id === entry.card_print_id);
  const pct = card ? signedPct(card.change_pct) : null;
  if (!card || pct === null) return { kind: "none", reason: "Not priced at both ends of this window" };
  return { kind: "change", pct, direction: direction(card.change_pct) };
}
