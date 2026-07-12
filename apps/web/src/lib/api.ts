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
    // A `detail` field instead means the proxy successfully forwarded a real
    // FastAPI error response (e.g. a 400/422/502 from the backend itself).
    const details = await res
      .json()
      .catch(
        () =>
          null as {
            error?: string;
            detail?: string;
            backend_status?: number;
            body_preview?: string;
          } | null,
      );
    if (details?.error) {
      throw new AdminProxyError(
        details.error,
        details.backend_status,
        details.body_preview,
      );
    }
    if (details?.detail) {
      throw new Error(details.detail);
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

export const COLLECTION_IMPORT_MODES = ["upsert", "append"] as const;
export type CollectionImportMode = (typeof COLLECTION_IMPORT_MODES)[number];

export interface CollectionImportRowError {
  row_number: number;
  card_code: string | null;
  error: string;
}

export interface CollectionImportPreviewRow {
  row_number: number;
  card_code: string;
  matched_card_id: number;
  action: string;
  quantity: number;
  status: string;
}

export interface CollectionImportSummary {
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  created: number;
  updated: number;
  skipped: number;
}

export interface CollectionImportResponse {
  dry_run: boolean;
  mode: string;
  summary: CollectionImportSummary;
  errors: CollectionImportRowError[];
  preview: CollectionImportPreviewRow[];
}

function filenameFromContentDisposition(value: string | null): string | null {
  if (!value) return null;
  const match = /filename=([^;]+)/.exec(value);
  return match ? match[1].trim().replace(/^"|"$/g, "") : null;
}

/** Downloads /collection/export.csv through the Next.js proxy (see
 * src/app/api/collection/export/route.ts) and triggers a browser file
 * download, using the filename the backend set via Content-Disposition. */
export async function downloadCollectionCsv(): Promise<void> {
  const res = await fetch("/api/collection/export", {
    headers: adminHeaders(),
    cache: "no-store",
  });

  if (!res.ok) {
    const details = await res
      .json()
      .catch(() => null as { error?: string; detail?: string } | null);
    throw new Error(
      details?.error || details?.detail || `Export failed with status ${res.status}`,
    );
  }

  const blob = await res.blob();
  const filename =
    filenameFromContentDisposition(res.headers.get("content-disposition")) ||
    "collection_export.csv";

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/** Uploads a collection CSV through the Next.js proxy (see
 * src/app/api/collection/import/route.ts). dry_run defaults to true on the
 * backend if omitted, but callers here always pass it explicitly. */
export async function importCollectionCsv(
  file: File,
  params: { dryRun: boolean; mode: CollectionImportMode },
): Promise<CollectionImportResponse> {
  const query = new URLSearchParams({
    dry_run: String(params.dryRun),
    mode: params.mode,
  });

  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`/api/collection/import?${query.toString()}`, {
    method: "POST",
    headers: adminHeaders(),
    body: formData,
  });

  const details = await res
    .json()
    .catch(
      () =>
        null as
          | (Partial<CollectionImportResponse> & { error?: string; detail?: string })
          | null,
    );

  if (!res.ok || !details) {
    throw new Error(
      details?.error || details?.detail || `Import failed with status ${res.status}`,
    );
  }

  return details as CollectionImportResponse;
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

export interface MarketReportPortfolioSnapshot {
  total_cost_basis_jpy: number | null;
  retail_value_jpy: number | null;
  liquidation_value_jpy: number | null;
  market_floor_value_jpy: number | null;
  pnl_vs_market_floor_jpy: number | null;
  pnl_vs_market_floor_pct: number | null;
  items_missing_cost_basis: number;
  items_missing_prices: number;
}

export interface MarketReportOpportunitySummary {
  total_opportunities: number;
  highest_score: number | null;
  average_score: number | null;
  by_category: Record<string, number>;
}

export interface MarketReportTopOpportunities {
  top_5: MarketOpportunity[];
  top_buy: MarketOpportunity | null;
  top_sell: MarketOpportunity | null;
  top_momentum: MarketOpportunity | null;
  top_drop: MarketOpportunity | null;
  top_owned: MarketOpportunity | null;
  top_data_quality: MarketOpportunity | null;
}

export interface MarketReportCollectionQuality {
  missing_purchase_price_count: number;
  missing_condition_count: number;
  missing_target_sell_count: number;
  total_quality_issues: number;
}

export interface MarketReportSignalEventSummary {
  open_events: number;
  watching_events: number;
  dismissed_events: number;
  resolved_events: number;
  most_common_signal_type: string | null;
  most_common_suggested_action: string | null;
}

export interface MarketReportSummary {
  total_opportunities: number;
  highest_score: number | null;
  average_score: number | null;
}

export interface MarketIntelligenceReport {
  id: number;
  created_at: string;
  report_date: string;
  summary: MarketReportSummary;
  portfolio_snapshot: MarketReportPortfolioSnapshot;
  opportunity_summary: MarketReportOpportunitySummary;
  top_opportunities: MarketReportTopOpportunities;
  collection_quality: MarketReportCollectionQuality;
  signal_event_summary: MarketReportSignalEventSummary;
  deterministic_summary_lines: string[];
  payload: Record<string, unknown>;
}

export interface MarketIntelligenceReportSummary {
  id: number;
  created_at: string;
  report_date: string;
  total_opportunities: number;
  highest_score: number | null;
  average_score: number | null;
  buy_opportunities_count: number;
  sell_opportunities_count: number;
  momentum_count: number;
  drop_count: number;
  data_quality_count: number;
  owned_count: number;
  portfolio_market_floor_value_jpy: number | null;
  portfolio_retail_value_jpy: number | null;
  portfolio_liquidation_value_jpy: number | null;
  portfolio_pnl_vs_market_floor_jpy: number | null;
}

export interface MarketIntelligenceReportListResponse {
  reports: MarketIntelligenceReportSummary[];
  total: number;
  limit: number;
  offset: number;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/market/report/latest/route.ts) - same reasoning as
 * fetchMarketSignals. Throws AdminNotFoundError when no report has been
 * generated yet. */
export function fetchLatestMarketReport(): Promise<MarketIntelligenceReport> {
  return fetchAdminJson<MarketIntelligenceReport>("/api/market/report/latest");
}

/** Routed through the Next.js server proxy (see
 * src/app/api/market/reports/route.ts). */
export function fetchMarketReports(params?: {
  limit?: number;
  offset?: number;
}): Promise<MarketIntelligenceReportListResponse> {
  const query = new URLSearchParams();
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return fetchAdminJson<MarketIntelligenceReportListResponse>(
    `/api/market/reports${qs ? `?${qs}` : ""}`,
  );
}

/** Routed through the Next.js server proxy (see
 * src/app/api/market/reports/[id]/route.ts). */
export function fetchMarketReport(reportId: number): Promise<MarketIntelligenceReport> {
  return fetchAdminJson<MarketIntelligenceReport>(`/api/market/reports/${reportId}`);
}

export const ADMIN_ACTION_SOURCES = ["all", "yuyutei", "snkrdunk"] as const;

export interface RefreshPricesRequest {
  source: string;
  limit?: number | null;
  dry_run?: boolean;
}

export interface RefreshPricesResponse {
  run_id: number | null;
  job_id: string | null;
  status: string | null;
  warnings: string[];
}

export interface SnapshotPortfolioResponse {
  snapshot_id: number;
}

export interface SnapshotMarketSignalsResponse {
  created_count: number;
  updated_count: number;
  resolved_count: number;
}

export interface GenerateMarketReportResponse {
  report_id: number;
}

export interface FullMarketRefreshRequest {
  source: string;
  limit?: number | null;
  dry_run?: boolean;
}

export interface FullMarketRefreshResponse {
  price_refresh_run_id: number | null;
  portfolio_snapshot_id: number | null;
  market_signal_snapshot: {
    created: number;
    updated: number;
    resolved: number;
  };
  market_report_id: number | null;
  dry_run: boolean;
  warnings: string[];
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/actions/refresh-prices/route.ts) - same reasoning as
 * fetchCardAudit. */
export function triggerRefreshPrices(
  body: RefreshPricesRequest,
): Promise<RefreshPricesResponse> {
  return fetchAdminJson<RefreshPricesResponse>("/api/admin/actions/refresh-prices", {
    method: "POST",
    body,
  });
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/actions/snapshot-portfolio/route.ts). */
export function triggerSnapshotPortfolio(): Promise<SnapshotPortfolioResponse> {
  return fetchAdminJson<SnapshotPortfolioResponse>("/api/admin/actions/snapshot-portfolio", {
    method: "POST",
  });
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/actions/snapshot-market-signals/route.ts). */
export function triggerSnapshotMarketSignals(): Promise<SnapshotMarketSignalsResponse> {
  return fetchAdminJson<SnapshotMarketSignalsResponse>(
    "/api/admin/actions/snapshot-market-signals",
    { method: "POST" },
  );
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/actions/generate-market-report/route.ts). */
export function triggerGenerateMarketReport(): Promise<GenerateMarketReportResponse> {
  return fetchAdminJson<GenerateMarketReportResponse>(
    "/api/admin/actions/generate-market-report",
    { method: "POST" },
  );
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/actions/full-market-refresh/route.ts). */
export function triggerFullMarketRefresh(
  body: FullMarketRefreshRequest,
): Promise<FullMarketRefreshResponse> {
  return fetchAdminJson<FullMarketRefreshResponse>("/api/admin/actions/full-market-refresh", {
    method: "POST",
    body,
  });
}

export interface SendMarketReportDigestRequest {
  dry_run?: boolean;
  force?: boolean;
}

export interface SendMarketReportDigestResponse {
  report_id: number | null;
  status: string | null;
  sent: boolean;
  skipped_reason: string | null;
  message_preview: string | null;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/actions/send-market-report-digest/route.ts). */
export function triggerSendMarketReportDigest(
  body: SendMarketReportDigestRequest,
): Promise<SendMarketReportDigestResponse> {
  return fetchAdminJson<SendMarketReportDigestResponse>(
    "/api/admin/actions/send-market-report-digest",
    { method: "POST", body },
  );
}

export const MARKET_WORKFLOW_RUN_STATUSES = [
  "running",
  "success",
  "partial_success",
  "failed",
] as const;

export interface RunMarketWorkflowRequest {
  source: string;
  limit?: number | null;
  send_telegram?: boolean;
  dry_run?: boolean;
}

export interface RunMarketWorkflowResponse {
  market_workflow_run_id: number | null;
  status: string | null;
  price_refresh_run_id: number | null;
  portfolio_snapshot_id: number | null;
  market_signal_snapshot: {
    created: number;
    updated: number;
    resolved: number;
  };
  market_report_id: number | null;
  telegram_digest_status: string | null;
  warnings: string[];
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/actions/run-market-workflow/route.ts). */
export function triggerRunMarketWorkflow(
  body: RunMarketWorkflowRequest,
): Promise<RunMarketWorkflowResponse> {
  return fetchAdminJson<RunMarketWorkflowResponse>(
    "/api/admin/actions/run-market-workflow",
    { method: "POST", body },
  );
}

export interface MarketWorkflowRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  source: string;
  limit: number | null;
  send_telegram: boolean;
  price_refresh_run_id: number | null;
  portfolio_snapshot_id: number | null;
  market_report_id: number | null;
  signal_events_created: number;
  signal_events_updated: number;
  signal_events_resolved: number;
  telegram_digest_status: string | null;
  warnings: string[];
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface MarketWorkflowRunListResponse {
  items: MarketWorkflowRun[];
  total: number;
  limit: number;
  offset: number;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/market-workflow-runs/route.ts) - same reasoning as
 * fetchMarketSignals. */
export function fetchMarketWorkflowRuns(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<MarketWorkflowRunListResponse> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return fetchAdminJson<MarketWorkflowRunListResponse>(
    `/api/admin/market-workflow-runs${qs ? `?${qs}` : ""}`,
  );
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/market-workflow-runs/[id]/route.ts). */
export function fetchMarketWorkflowRun(runId: number): Promise<MarketWorkflowRun> {
  return fetchAdminJson<MarketWorkflowRun>(`/api/admin/market-workflow-runs/${runId}`);
}

// --- Backup / restore --------------------------------------------------

export const BACKUP_RESTORE_MODES = ["merge", "replace"] as const;
export type BackupRestoreMode = (typeof BACKUP_RESTORE_MODES)[number];

export interface BackupValidateResponse {
  valid: boolean;
  backup_version: number | null;
  summary: Record<string, number>;
  warnings: string[];
  errors: string[];
}

export interface BackupRestoreResponse {
  dry_run: boolean;
  mode: string;
  valid: boolean;
  backup_version: number | null;
  summary: {
    created: Record<string, number>;
    updated: Record<string, number>;
    deleted: Record<string, number>;
    skipped: Record<string, number>;
  };
  warnings: string[];
  errors: string[];
  preview: Record<string, Record<string, number>>;
}

/** Downloads /admin/backup/export through the Next.js proxy (see
 * src/app/api/admin/backup/export/route.ts) and triggers a browser file
 * download, using the filename the backend set via Content-Disposition. */
export async function downloadBackup(params: {
  includePrices: boolean;
  includeRawSnapshots: boolean;
  includeRefreshRuns: boolean;
}): Promise<void> {
  const query = new URLSearchParams({
    include_prices: String(params.includePrices),
    include_raw_snapshots: String(params.includeRawSnapshots),
    include_refresh_runs: String(params.includeRefreshRuns),
  });

  const res = await fetch(`/api/admin/backup/export?${query.toString()}`, {
    headers: adminHeaders(),
    cache: "no-store",
  });

  if (res.status === 401) throw new AdminAuthRequiredError();
  if (!res.ok) {
    const details = await res
      .json()
      .catch(() => null as { error?: string; detail?: string } | null);
    throw new Error(
      details?.error || details?.detail || `Export failed with status ${res.status}`,
    );
  }

  const blob = await res.blob();
  const filename =
    filenameFromContentDisposition(res.headers.get("content-disposition")) ||
    "opcg_backup.json";

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

async function postBackupFile<T>(
  path: string,
  file: File,
  query: Record<string, string>,
): Promise<T> {
  const qs = new URLSearchParams(query).toString();
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${path}${qs ? `?${qs}` : ""}`, {
    method: "POST",
    headers: adminHeaders(),
    body: formData,
  });

  if (res.status === 401) throw new AdminAuthRequiredError();

  const details = await res
    .json()
    .catch(() => null as (Partial<T> & { error?: string; detail?: string }) | null);

  if (!res.ok || !details) {
    throw new Error(
      (details as { error?: string; detail?: string } | null)?.error ||
        (details as { error?: string; detail?: string } | null)?.detail ||
        `Request failed with status ${res.status}`,
    );
  }

  return details as T;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/backup/validate/route.ts). */
export function validateBackup(file: File): Promise<BackupValidateResponse> {
  return postBackupFile<BackupValidateResponse>("/api/admin/backup/validate", file, {});
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/backup/restore/route.ts). */
export function restoreBackup(
  file: File,
  params: { dryRun: boolean; mode: BackupRestoreMode; confirm?: string },
): Promise<BackupRestoreResponse> {
  const query: Record<string, string> = {
    dry_run: String(params.dryRun),
    mode: params.mode,
  };
  if (params.confirm) query.confirm = params.confirm;
  return postBackupFile<BackupRestoreResponse>("/api/admin/backup/restore", file, query);
}
