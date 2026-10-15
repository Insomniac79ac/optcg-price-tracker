/** The v1 watchlist API shape (services/api/app/accounts/schemas.py
 * WatchlistOut) and the words /watchlist renders it with (Collector v1 S8,
 * PLAN §E3).
 *
 * Nothing here computes a price, a distance or a change: the value, the gap to
 * the target and the 7D change are the API's. These helpers only choose words
 * for what the API says, including why a number is missing. */

import { direction, signedPct, unavailableReason, yen, type PrintSummary } from "@/lib/collection";

export interface WatchEntry {
  id: number;
  card_print_id: number | null;
  resolution: "exact" | "unresolved";
  target_jpy: number | null;
  note: string | null;
  legacy_card_id: number | null;
  created_at: string;
  updated_at: string;
  print: PrintSummary | null;
  value_status: "priced" | "no_price" | "unresolved";
  value_jpy: number | null;
  /** value_jpy − target_jpy, from the API; null without both. */
  target_gap_jpy: number | null;
  /** When the freshest source behind value_jpy was read. Optional so an older
   * API without the field still parses (shown as unknown). */
  checked_at?: string | null;
  change_7d_pct?: string | null;
  change_7d_reason?: string | null;
}

export interface WatchlistResponse {
  currency: "JPY";
  as_of: string | null;
  entries: WatchEntry[];
  change_7d_from?: string | null;
  change_7d_missing_dates?: string[];
}

/** "¥1,200 above your target" / "¥300 below your target" / "At your target",
 * from the API's gap. null when there is no target or no price. */
export function targetDistance(entry: Pick<WatchEntry, "target_jpy" | "target_gap_jpy">): string | null {
  if (entry.target_jpy === null || entry.target_gap_jpy === null) return null;
  if (entry.target_gap_jpy === 0) return "At your target";
  return `${yen(Math.abs(entry.target_gap_jpy))} ${entry.target_gap_jpy > 0 ? "above" : "below"} your target`;
}

/** "Checked 3 h ago", "Checked 2 days ago"; "Check time unknown" when the API
 * does not know. Never invents a time. */
export function checkedAgo(iso: string | null | undefined, now: Date): string {
  if (!iso) return "Check time unknown";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "Check time unknown";
  const minutes = Math.max(0, Math.floor((now.getTime() - at.getTime()) / 60_000));
  if (minutes < 60) return minutes <= 1 ? "Checked just now" : `Checked ${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `Checked ${hours} h ago`;
  return `Checked ${Math.floor(hours / 24)} days ago`;
}

// Per-version reasons (services/app/market_value.py _comparability_reason),
// in collector words. Window-level reasons fall through to unavailableReason.
const VERSION_REASONS: Record<string, string> = {
  entrant: "Not priced 7 days ago",
  leaver: "No price today",
  unusable_value: "No usable price at one end",
  index_version_changed: "How we price this card changed this week",
  source_semantics_version_changed: "How we price this card changed this week",
  contributor_set_unavailable: "Price sources unknown at one end",
  contributor_set_changed: "Price sources changed this week",
  unresolved: "Needs a version",
};

export type WatchChange = { kind: "change"; pct: string; direction: "up" | "down" | "flat" } | { kind: "none"; reason: string };

/** The 7D change for one row: the API's figure, or why there is none. An
 * unavailable change is never shown as 0%. */
export function watchChange(entry: WatchEntry, list: Pick<WatchlistResponse, "change_7d_missing_dates">): WatchChange {
  const pct = signedPct(entry.change_7d_pct);
  if (pct !== null) return { kind: "change", pct, direction: direction(entry.change_7d_pct) };
  const reason = entry.change_7d_reason ?? null;
  if (reason && VERSION_REASONS[reason]) return { kind: "none", reason: VERSION_REASONS[reason] };
  if (!("change_7d_reason" in entry)) return { kind: "none", reason: "Not available right now" };
  return { kind: "none", reason: unavailableReason({ reason, missing_dates: list.change_7d_missing_dates ?? [] }) };
}
