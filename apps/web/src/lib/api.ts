export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Card {
  id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  set_code: string;
  rarity: string;
  variant: string | null;
  language: string;
  image_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface PriceObservation {
  id: number;
  card_id: number;
  source_id: number;
  source: string;
  observed_at: string;
  price_type: string;
  price_jpy: number;
  condition_label: string | null;
  stock_status: string | null;
  listing_count: number | null;
  raw_snapshot_id: number | null;
}

export interface MarketPrice {
  source: string;
  price_type: string;
  price_jpy: number;
  observed_at: string;
  condition_label: string | null;
  stock_status: string | null;
  listing_count: number | null;
}

export interface MarketSignals {
  change_24h_pct: number | null;
  change_7d_pct: number | null;
  change_30d_pct: number | null;
  yuyutei_spread_jpy: number | null;
  snkrdunk_floor_vs_yuyutei_buy_jpy: number | null;
}

export interface MarketMover {
  card_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  set_code: string;
  rarity: string;
  variant: string | null;
  language: string;
  latest_prices: MarketPrice[];
  signals: MarketSignals;
}

export interface SnkrdunkCandidate {
  id: number;
  discovery_run_id: number | null;
  source_url: string;
  title: string | null;
  price_jpy: number | null;
  image_url: string | null;
  listing_count: number | null;
  condition_label: string | null;
  normalized_title: string | null;
  detected_card_code: string | null;
  detected_set_code: string | null;
  detected_rarity: string | null;
  detected_variant: string | null;
  match_status: string;
  matched_card_id: number | null;
  match_confidence: number | null;
  created_at: string;
  updated_at: string;
  matched_card: Card | null;
}

export interface SnkrdunkCandidateList {
  items: SnkrdunkCandidate[];
  total: number;
  limit: number;
  offset: number;
}

export interface PriceRefreshRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  scraping_mode: string;
  source_filter: string | null;
  limit_count: number;
  dry_run: boolean;
  mappings_checked: number;
  snapshots_created: number;
  observations_parsed: number;
  observations_inserted: number;
  observations_skipped_duplicate: number;
  mappings_failed: number;
  error_message: string | null;
}

export interface PriceRefreshRunList {
  items: PriceRefreshRun[];
  total: number;
  limit: number;
  offset: number;
}

export interface AlertEvent {
  id: number;
  created_at: string;
  event_type: string;
  card_id: number | null;
  card_code: string | null;
  card_name: string | null;
  source_name: string | null;
  price_observation_id: number | null;
  refresh_run_id: number | null;
  title: string;
  message: string;
  dedupe_key: string;
  sent_at: string | null;
  status: string;
  error_message: string | null;
}

export interface AlertEventList {
  items: AlertEvent[];
  total: number;
  limit: number;
  offset: number;
}

export interface CardAuditIssue {
  issue_type: string;
  severity: string;
  card_ids: number[];
  card_code: string | null;
  message: string;
  suggested_action: string;
  details?: Record<string, unknown> | null;
}

export interface CardAuditSummary {
  total_cards: number;
  total_issues: number;
  critical_issues: number;
  warning_issues: number;
}

export interface CardAuditReport {
  summary: CardAuditSummary;
  issues: CardAuditIssue[];
}

/** A response is a valid CardAuditReport as long as it has a `summary`
 * object and an `issues` array - an empty `issues` array is a perfectly
 * valid ("no catalog issues found") result, not missing data. Only the
 * shape is checked here; field-level correctness is the backend's job. */
export function isCardAuditReport(data: unknown): data is CardAuditReport {
  if (!data || typeof data !== "object") return false;
  const candidate = data as { summary?: unknown; issues?: unknown };
  return (
    !!candidate.summary &&
    typeof candidate.summary === "object" &&
    Array.isArray(candidate.issues)
  );
}

export interface AlertRule {
  id: number;
  created_at: string;
  updated_at: string;
  name: string;
  rule_type: string;
  source_name: string | null;
  price_type: string | null;
  threshold_pct: number | null;
  is_active: boolean;
}

export interface CollectionItem {
  id: number;
  card_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  set_code: string;
  rarity: string;
  variant: string | null;
  language: string;
  quantity: number;
  condition_label: string | null;
  purchase_price_jpy: number | null;
  purchase_date: string | null;
  purchase_source: string | null;
  target_sell_price_jpy: number | null;
  notes: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface CollectionItemList {
  items: CollectionItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface CollectionSummary {
  total_items: number;
  total_quantity: number;
  total_cost_basis_jpy: number;
  items_with_purchase_price: number;
  items_missing_purchase_price: number;
  items_by_status: Record<string, number>;
}

export const COLLECTION_STATUS_OPTIONS = [
  "hold",
  "watch",
  "sell",
  "sold",
  "grading",
] as const;

export interface CollectionItemInput {
  card_id: number;
  quantity?: number;
  condition_label?: string | null;
  purchase_price_jpy?: number | null;
  purchase_date?: string | null;
  purchase_source?: string | null;
  target_sell_price_jpy?: number | null;
  notes?: string | null;
  status?: string;
}

const ADMIN_TOKEN_STORAGE_KEY = "admin_token";

export function getAdminToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ADMIN_TOKEN_STORAGE_KEY);
}

export function setAdminToken(token: string): void {
  window.localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, token);
}

export function clearAdminToken(): void {
  window.localStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY);
}

export class AdminAuthRequiredError extends Error {
  constructor() {
    super("Admin token required");
    this.name = "AdminAuthRequiredError";
  }
}

export class AdminNotFoundError extends Error {
  constructor() {
    super("Not found");
    this.name = "AdminNotFoundError";
  }
}

export class AdminTimeoutError extends Error {
  constructor() {
    super("Request timed out");
    this.name = "AdminTimeoutError";
  }
}

export class AdminNetworkError extends Error {
  constructor(message = "Network error") {
    super(message);
    this.name = "AdminNetworkError";
  }
}

/** Thrown when a response was successfully fetched and parsed as JSON, but
 * doesn't have the shape the caller needs (missing entirely, or missing
 * required fields) - distinct from an empty-but-valid result. */
export class AdminInvalidResponseError extends Error {
  constructor() {
    super("No data received from API");
    this.name = "AdminInvalidResponseError";
  }
}

/** Thrown when the Next.js proxy route itself responded, but reported that
 * it couldn't get a usable JSON response from the backend API (backend
 * unreachable, empty body, or non-JSON body). Carries the structured fields
 * the proxy route attaches so the UI can show something more useful than a
 * generic failure message. */
export class AdminProxyError extends Error {
  backendStatus?: number;
  bodyPreview?: string;

  constructor(message: string, backendStatus?: number, bodyPreview?: string) {
    super(message);
    this.name = "AdminProxyError";
    this.backendStatus = backendStatus;
    this.bodyPreview = bodyPreview;
  }
}

function adminHeaders(): Record<string, string> {
  const token = getAdminToken();
  return token ? { "X-Admin-Token": token } : {};
}

const ADMIN_FETCH_TIMEOUT_MS = 15_000;

/** Fetches a relative (same-origin) admin path - e.g. a Next.js API proxy
 * route - attaching the stored admin token if one exists, but still trying
 * the request without it otherwise (some admin endpoints allow unauthenticated
 * access in development). Distinguishes 401/404/timeout/network failures so
 * callers can render a state more specific than a generic error.
 *
 * Defaults to GET; pass `options.method`/`options.body` for mutations
 * (POST/PATCH) through the same proxy-aware error handling. */
export async function fetchAdminJson<T>(
  path: string,
  options?: { method?: string; body?: unknown },
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), ADMIN_FETCH_TIMEOUT_MS);

  let res: Response;
  try {
    res = await fetch(path, {
      method: options?.method,
      cache: "no-store",
      headers: {
        ...adminHeaders(),
        ...(options?.body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: options?.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new AdminTimeoutError();
    }
    throw new AdminNetworkError(
      err instanceof Error ? err.message : "Network error",
    );
  } finally {
    clearTimeout(timeout);
  }

  if (res.status === 401) throw new AdminAuthRequiredError();
  if (res.status === 404) throw new AdminNotFoundError();
  if (!res.ok) {
    // The proxy route reports backend-fetch/parsing failures as a JSON body
    // with an `error` field rather than an HTTP-level failure, so surface
    // that message and its details instead of a generic status-code error.
    const details = await res
      .json()
      .catch(() => null as { error?: string; backend_status?: number; body_preview?: string } | null);
    if (details?.error) {
      throw new AdminProxyError(
        details.error,
        details.backend_status,
        details.body_preview,
      );
    }
    throw new Error(`Request to ${path} failed with status ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    headers: adminHeaders(),
  });
  if (res.status === 401) throw new AdminAuthRequiredError();
  if (!res.ok) {
    throw new Error(`Request to ${path} failed with status ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { ...adminHeaders(), ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) throw new AdminAuthRequiredError();
  if (!res.ok) {
    throw new Error(`Request to ${path} failed with status ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "PATCH",
    headers: { ...adminHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 401) throw new AdminAuthRequiredError();
  if (!res.ok) {
    throw new Error(`Request to ${path} failed with status ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function apiDelete(path: string): Promise<void> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "DELETE",
    headers: adminHeaders(),
  });
  if (res.status === 401) throw new AdminAuthRequiredError();
  if (!res.ok) {
    throw new Error(`Request to ${path} failed with status ${res.status}`);
  }
}

export function fetchCards(): Promise<Card[]> {
  return apiGet<Card[]>("/cards");
}

export function fetchCard(id: string | number): Promise<Card> {
  return apiGet<Card>(`/cards/${id}`);
}

export function fetchCardPrices(
  id: string | number,
): Promise<PriceObservation[]> {
  return apiGet<PriceObservation[]>(`/cards/${id}/prices`);
}

export function fetchMarketMovers(params?: {
  source?: string;
  price_type?: string;
  rarity?: string;
  variant?: string;
  limit?: number;
  offset?: number;
}): Promise<MarketMover[]> {
  const query = new URLSearchParams();
  if (params?.source) query.set("source", params.source);
  if (params?.price_type) query.set("price_type", params.price_type);
  if (params?.rarity) query.set("rarity", params.rarity);
  if (params?.variant) query.set("variant", params.variant);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return apiGet<MarketMover[]>(`/market/movers${qs ? `?${qs}` : ""}`);
}

export function fetchSnkrdunkCandidates(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<SnkrdunkCandidateList> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return apiGet<SnkrdunkCandidateList>(
    `/snkrdunk/candidates${qs ? `?${qs}` : ""}`,
  );
}

export function matchSnkrdunkCandidate(
  candidateId: number,
  cardId: number,
): Promise<SnkrdunkCandidate> {
  return apiPost<SnkrdunkCandidate>(
    `/snkrdunk/candidates/${candidateId}/match`,
    { card_id: cardId, manual_verified: true },
  );
}

export function rejectSnkrdunkCandidate(
  candidateId: number,
): Promise<SnkrdunkCandidate> {
  return apiPost<SnkrdunkCandidate>(
    `/snkrdunk/candidates/${candidateId}/reject`,
  );
}

export function fetchRefreshRuns(params?: {
  status?: string;
  source_filter?: string;
  limit?: number;
  offset?: number;
}): Promise<PriceRefreshRunList> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.source_filter) query.set("source_filter", params.source_filter);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return apiGet<PriceRefreshRunList>(
    `/admin/refresh-runs${qs ? `?${qs}` : ""}`,
  );
}

export function fetchRefreshRun(runId: number): Promise<PriceRefreshRun> {
  return apiGet<PriceRefreshRun>(`/admin/refresh-runs/${runId}`);
}

export function fetchAlertEvents(params?: {
  status?: string;
  event_type?: string;
  limit?: number;
  offset?: number;
}): Promise<AlertEventList> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.event_type) query.set("event_type", params.event_type);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return apiGet<AlertEventList>(`/admin/alert-events${qs ? `?${qs}` : ""}`);
}

export function fetchAlertEvent(eventId: number): Promise<AlertEvent> {
  return apiGet<AlertEvent>(`/admin/alert-events/${eventId}`);
}

export function fetchAlertRules(): Promise<AlertRule[]> {
  return apiGet<AlertRule[]>("/admin/alert-rules");
}

export function updateAlertRule(
  ruleId: number,
  body: { is_active?: boolean; threshold_pct?: number },
): Promise<AlertRule> {
  return apiPatch<AlertRule>(`/admin/alert-rules/${ruleId}`, body);
}

export function fetchCollectionItems(params?: {
  status?: string;
  card_code?: string;
  card_id?: number;
  limit?: number;
  offset?: number;
}): Promise<CollectionItemList> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.card_code) query.set("card_code", params.card_code);
  if (params?.card_id !== undefined) query.set("card_id", String(params.card_id));
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return apiGet<CollectionItemList>(`/collection${qs ? `?${qs}` : ""}`);
}

export function fetchCollectionSummary(): Promise<CollectionSummary> {
  return apiGet<CollectionSummary>("/collection/summary");
}

export interface YuyuteiPriceSnapshot {
  price_jpy: number;
  observed_at: string;
}

export interface SnkrdunkFloorSnapshot {
  price_jpy: number;
  observed_at: string;
  listing_count: number | null;
  condition_label: string | null;
}

export interface ValuationLatestPrices {
  yuyutei_sell: YuyuteiPriceSnapshot | null;
  yuyutei_buy: YuyuteiPriceSnapshot | null;
  snkrdunk_floor: SnkrdunkFloorSnapshot | null;
}

export interface ValuationDetail {
  retail_value_jpy: number | null;
  liquidation_value_jpy: number | null;
  market_floor_value_jpy: number | null;
  pnl_vs_retail_jpy: number | null;
  pnl_vs_retail_pct: number | null;
  pnl_vs_liquidation_jpy: number | null;
  pnl_vs_liquidation_pct: number | null;
  pnl_vs_market_floor_jpy: number | null;
  pnl_vs_market_floor_pct: number | null;
}

export interface ValuationFlags {
  missing_yuyutei_sell: boolean;
  missing_yuyutei_buy: boolean;
  missing_snkrdunk_floor: boolean;
  missing_cost_basis: boolean;
  above_target_sell: boolean;
}

export interface PortfolioValuationItem {
  collection_item_id: number;
  card_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  set_code: string;
  rarity: string;
  variant: string | null;
  language: string;
  quantity: number;
  condition_label: string | null;
  purchase_price_jpy: number | null;
  cost_basis_jpy: number | null;
  target_sell_price_jpy: number | null;
  latest_prices: ValuationLatestPrices;
  valuations: ValuationDetail;
  flags: ValuationFlags;
}

export type ValuationBasis = "market_floor" | "retail";

export interface BestWorstPerformer {
  collection_item_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  pnl_jpy: number;
  pnl_pct: number | null;
  basis: ValuationBasis;
}

export interface RetailLiquidationGap {
  collection_item_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  gap_jpy: number;
  gap_pct: number | null;
}

export interface HighestValueItem {
  collection_item_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  value_jpy: number;
  basis: ValuationBasis;
}

export interface PortfolioValuationInsights {
  best_performing_item: BestWorstPerformer | null;
  worst_performing_item: BestWorstPerformer | null;
  largest_retail_liquidation_gap: RetailLiquidationGap | null;
  highest_value_item: HighestValueItem | null;
}

export interface PortfolioValuationSummary {
  total_items: number;
  total_quantity: number;
  total_cost_basis_jpy: number;
  retail_value_jpy: number;
  liquidation_value_jpy: number;
  market_floor_value_jpy: number;
  pnl_vs_retail_jpy: number;
  pnl_vs_retail_pct: number;
  pnl_vs_liquidation_jpy: number;
  pnl_vs_liquidation_pct: number;
  pnl_vs_market_floor_jpy: number;
  pnl_vs_market_floor_pct: number;
  items_missing_yuyutei_sell: number;
  items_missing_yuyutei_buy: number;
  items_missing_snkrdunk_floor: number;
  items_missing_cost_basis: number;
  cards_above_target_sell: number;
  insights: PortfolioValuationInsights;
}

export interface PortfolioValuation {
  summary: PortfolioValuationSummary;
  items: PortfolioValuationItem[];
}

export function fetchCollectionValuation(): Promise<PortfolioValuation> {
  return apiGet<PortfolioValuation>("/collection/valuation");
}

export interface PortfolioValuationSnapshot {
  id: number;
  created_at: string;
  total_items: number;
  total_quantity: number;
  total_cost_basis_jpy: number | null;
  retail_value_jpy: number | null;
  liquidation_value_jpy: number | null;
  market_floor_value_jpy: number | null;
  pnl_vs_retail_jpy: number | null;
  pnl_vs_liquidation_jpy: number | null;
  pnl_vs_market_floor_jpy: number | null;
  items_missing_yuyutei_sell: number;
  items_missing_yuyutei_buy: number;
  items_missing_snkrdunk_floor: number;
  items_missing_cost_basis: number;
  cards_above_target_sell: number;
}

export function fetchCollectionValuationHistory(
  days: string,
): Promise<PortfolioValuationSnapshot[]> {
  const query = new URLSearchParams({ days });
  return apiGet<PortfolioValuationSnapshot[]>(
    `/collection/valuation/history?${query.toString()}`,
  );
}

export function createCollectionItem(
  body: CollectionItemInput,
): Promise<CollectionItem> {
  return apiPost<CollectionItem>("/collection", body);
}

export function updateCollectionItem(
  itemId: number,
  body: Partial<CollectionItemInput>,
): Promise<CollectionItem> {
  return apiPatch<CollectionItem>(`/collection/${itemId}`, body);
}

export function deleteCollectionItem(itemId: number): Promise<void> {
  return apiDelete(`/collection/${itemId}`);
}

export const MARKET_SIGNAL_TYPES = [
  "price_up_7d",
  "price_down_7d",
  "price_up_30d",
  "price_down_30d",
  "yuyutei_buy_sell_spread_compressed",
  "yuyutei_buy_sell_spread_wide",
  "snkrdunk_floor_below_yuyutei_sell",
  "snkrdunk_floor_above_yuyutei_sell",
  "owned_above_target_sell",
  "owned_below_cost_basis",
  "missing_recent_price",
  "stale_mapping_price",
] as const;

export interface MarketSignalLatestPrices {
  yuyutei_sell: number | null;
  yuyutei_buy: number | null;
  snkrdunk_floor: number | null;
}

export interface MarketSignalMetrics {
  change_pct: number | null;
  spread_pct: number | null;
  gap_pct: number | null;
  gap_jpy: number | null;
}

export interface MarketSignal {
  signal_type: string;
  severity: string;
  card_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  set_code: string;
  rarity: string;
  variant: string | null;
  language: string;
  owned_quantity: number;
  latest_prices: MarketSignalLatestPrices;
  metrics: MarketSignalMetrics;
  message: string;
  suggested_action: string;
}

export interface MarketSignalsSummary {
  total_signals: number;
  by_signal_type: Record<string, number>;
  owned_signal_count: number;
  market_signal_count: number;
  data_quality_signal_count: number;
}

export interface MarketSignalsResponse {
  summary: MarketSignalsSummary;
  signals: MarketSignal[];
}

/** Routed through the Next.js server proxy (see
 * src/app/api/market/signals/route.ts) rather than NEXT_PUBLIC_API_URL,
 * since browser-side fetches to the backend's host port are unreliable in
 * Codespaces/forwarded-port environments - same reasoning as fetchCardAudit. */
export function fetchMarketSignals(params?: {
  signal_type?: string;
  set_code?: string;
  rarity?: string;
  source?: string;
  owned?: boolean;
  limit?: number;
  offset?: number;
}): Promise<MarketSignalsResponse> {
  const query = new URLSearchParams();
  if (params?.signal_type) query.set("signal_type", params.signal_type);
  if (params?.set_code) query.set("set_code", params.set_code);
  if (params?.rarity) query.set("rarity", params.rarity);
  if (params?.source) query.set("source", params.source);
  if (params?.owned !== undefined) query.set("owned", String(params.owned));
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return fetchAdminJson<MarketSignalsResponse>(
    `/api/market/signals${qs ? `?${qs}` : ""}`,
  );
}

export const MARKET_SIGNAL_EVENT_STATUSES = [
  "open",
  "watching",
  "dismissed",
  "resolved",
] as const;

export const MARKET_SUGGESTED_ACTIONS = [
  "review_buy_opportunity",
  "review_sell_opportunity",
  "monitor_momentum",
  "monitor_drop",
  "review_mapping",
  "update_prices",
  "add_collection_target",
  "none",
] as const;

export interface MarketSignalEvent {
  id: number;
  signal_type: string;
  status: string;
  severity: string;
  suggested_action: string | null;
  card_id: number | null;
  card_code: string | null;
  name_en: string | null;
  name_jp: string | null;
  set_code: string | null;
  rarity: string | null;
  variant: string | null;
  language: string | null;
  collection_item_id: number | null;
  owned_quantity: number;
  message: string | null;
  notes: string | null;
  first_seen_at: string;
  last_seen_at: string;
  seen_count: number;
  last_payload: Record<string, unknown> | null;
  dismissed_at: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MarketSignalEventsSummary {
  total_events: number;
  open_events: number;
  watching_events: number;
  dismissed_events: number;
  resolved_events: number;
  by_signal_type: Record<string, number>;
  by_suggested_action: Record<string, number>;
}

export interface MarketSignalEventListResponse {
  summary: MarketSignalEventsSummary;
  events: MarketSignalEvent[];
}

/** Routed through the Next.js server proxy (see
 * src/app/api/market/signal-events/route.ts) - same reasoning as
 * fetchMarketSignals. */
export function fetchMarketSignalEvents(params?: {
  status?: string;
  signal_type?: string;
  suggested_action?: string;
  card_code?: string;
  owned?: boolean;
  limit?: number;
  offset?: number;
}): Promise<MarketSignalEventListResponse> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.signal_type) query.set("signal_type", params.signal_type);
  if (params?.suggested_action) query.set("suggested_action", params.suggested_action);
  if (params?.card_code) query.set("card_code", params.card_code);
  if (params?.owned !== undefined) query.set("owned", String(params.owned));
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return fetchAdminJson<MarketSignalEventListResponse>(
    `/api/market/signal-events${qs ? `?${qs}` : ""}`,
  );
}

export function patchMarketSignalEvent(
  id: number,
  body: { status?: string; notes?: string },
): Promise<MarketSignalEvent> {
  return fetchAdminJson<MarketSignalEvent>(`/api/market/signal-events/${id}`, {
    method: "PATCH",
    body,
  });
}

export function dismissMarketSignalEvent(id: number): Promise<MarketSignalEvent> {
  return fetchAdminJson<MarketSignalEvent>(`/api/market/signal-events/${id}/dismiss`, {
    method: "POST",
  });
}

export function watchMarketSignalEvent(id: number): Promise<MarketSignalEvent> {
  return fetchAdminJson<MarketSignalEvent>(`/api/market/signal-events/${id}/watch`, {
    method: "POST",
  });
}

export function resolveMarketSignalEvent(id: number): Promise<MarketSignalEvent> {
  return fetchAdminJson<MarketSignalEvent>(`/api/market/signal-events/${id}/resolve`, {
    method: "POST",
  });
}

export const OPPORTUNITY_CATEGORIES = [
  "buy",
  "sell",
  "momentum",
  "drop",
  "data_quality",
  "owned",
] as const;

export interface MarketOpportunity {
  score: number;
  category: string;
  event_id: number;
  signal_type: string;
  status: string;
  severity: string;
  suggested_action: string | null;
  card_id: number | null;
  card_code: string | null;
  name_en: string | null;
  name_jp: string | null;
  set_code: string | null;
  rarity: string | null;
  variant: string | null;
  language: string | null;
  owned_quantity: number;
  message: string | null;
  first_seen_at: string;
  last_seen_at: string;
  seen_count: number;
  score_reasons: string[];
  last_payload: Record<string, unknown> | null;
}

export interface MarketOpportunitiesSummary {
  total_opportunities: number;
  average_score: number;
  highest_score: number;
  by_category: Record<string, number>;
}

export interface MarketOpportunitiesResponse {
  summary: MarketOpportunitiesSummary;
  opportunities: MarketOpportunity[];
}

/** Routed through the Next.js server proxy (see
 * src/app/api/market/opportunities/route.ts) - same reasoning as
 * fetchMarketSignals. */
export function fetchMarketOpportunities(params?: {
  category?: string;
  owned?: boolean;
  set_code?: string;
  rarity?: string;
  min_score?: number;
  limit?: number;
  offset?: number;
}): Promise<MarketOpportunitiesResponse> {
  const query = new URLSearchParams();
  if (params?.category) query.set("category", params.category);
  if (params?.owned !== undefined) query.set("owned", String(params.owned));
  if (params?.set_code) query.set("set_code", params.set_code);
  if (params?.rarity) query.set("rarity", params.rarity);
  if (params?.min_score !== undefined) query.set("min_score", String(params.min_score));
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return fetchAdminJson<MarketOpportunitiesResponse>(
    `/api/market/opportunities${qs ? `?${qs}` : ""}`,
  );
}

export async function fetchCardAudit(): Promise<CardAuditReport> {
  // Routed through the Next.js server proxy (see
  // src/app/api/admin/card-audit/route.ts) rather than NEXT_PUBLIC_API_URL,
  // since browser-side fetches to the backend's host port are unreliable in
  // Codespaces/forwarded-port environments.
  const data = await fetchAdminJson<unknown>("/api/admin/card-audit");
  if (!isCardAuditReport(data)) {
    throw new AdminInvalidResponseError();
  }
  return data;
}
