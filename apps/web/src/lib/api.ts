import { getSession } from "next-auth/react";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Standard pagination metadata block - see services/api/app/core/pagination.py.
 * Attached (as `pagination`) to every paginated list response; pages use it
 * to render "Showing X-Y of Z" + Previous/Next without re-deriving has_next/
 * has_previous from total/limit/offset themselves. */
export interface PaginationMeta {
  total: number;
  limit: number;
  offset: number;
  has_next: boolean;
  has_previous: boolean;
  next_offset: number | null;
  previous_offset: number | null;
}

export interface CollectorTag {
  id: number;
  name: string;
  slug: string;
  color: string | null;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface CollectorTagInput {
  name: string;
  color?: string | null;
  description?: string | null;
}

export interface CollectorGroup {
  id: number;
  name: string;
  slug: string;
  description: string | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface CollectorGroupInput {
  name: string;
  description?: string | null;
  sort_order?: number;
}

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
  tags: CollectorTag[];
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
  raw_text: string | null;
  normalized_title: string | null;
  detected_card_code: string | null;
  detected_set_code: string | null;
  detected_rarity: string | null;
  detected_variant: string | null;
  match_status: string;
  matched_card_id: number | null;
  match_confidence: number | null;
  best_match_card_id: number | null;
  best_match_score: number | null;
  best_match_confidence_label: string | null;
  created_at: string;
  updated_at: string;
  matched_card: Card | null;
}

export interface SnkrdunkCandidateList {
  items: SnkrdunkCandidate[];
  total: number;
  limit: number;
  offset: number;
  pagination: PaginationMeta;
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
  pagination: PaginationMeta;
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
  pagination: PaginationMeta;
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

export const GRADING_SUBMISSION_STATUSES = [
  "planned",
  "preparing",
  "submitted",
  "grading",
  "shipped_back",
  "received",
  "cancelled",
] as const;
export type GradingSubmissionStatus = (typeof GRADING_SUBMISSION_STATUSES)[number];

export const GRADING_COMPANY_OPTIONS = ["PSA", "BGS", "CGC", "ARS", "Other"] as const;

export interface GradingSubmission {
  id: number;
  collection_item_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  quantity: number;
  grading_company: string;
  submission_name: string | null;
  submission_status: string;
  declared_value_jpy: number | null;
  grading_fee_jpy: number | null;
  shipping_fee_jpy: number | null;
  insurance_fee_jpy: number | null;
  other_fee_jpy: number | null;
  total_cost_jpy: number | null;
  submitted_at: string | null;
  received_at: string | null;
  expected_return_date: string | null;
  tracking_number: string | null;
  final_grade: string | null;
  cert_number: string | null;
  graded_value_jpy: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface GradingSubmissionInput {
  collection_item_id: number;
  grading_company: string;
  submission_name?: string | null;
  submission_status?: string;
  declared_value_jpy?: number | null;
  grading_fee_jpy?: number | null;
  shipping_fee_jpy?: number | null;
  insurance_fee_jpy?: number | null;
  other_fee_jpy?: number | null;
  submitted_at?: string | null;
  received_at?: string | null;
  expected_return_date?: string | null;
  tracking_number?: string | null;
  final_grade?: string | null;
  cert_number?: string | null;
  graded_value_jpy?: number | null;
  notes?: string | null;
}

export interface GradingSubmissionList {
  items: GradingSubmission[];
  total: number;
  limit: number;
  offset: number;
  pagination: PaginationMeta;
}

export interface GradingSummary {
  total_submissions: number;
  by_status: Record<string, number>;
  total_declared_value_jpy: number;
  total_grading_cost_jpy: number;
  total_graded_value_jpy: number;
  total_unrealized_gain_after_grading_jpy: number;
  average_grade: number | null;
  items_waiting_return: number;
}

export interface GradingInfo {
  has_grading_submission: boolean;
  latest_status: string | null;
  grading_company: string | null;
  final_grade: string | null;
  total_grading_cost_jpy: number | null;
  graded_value_jpy: number | null;
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
  tags: CollectorTag[];
  groups: CollectorGroup[];
  grading_submissions: GradingSubmission[];
  latest_grading_status: string | null;
  created_at: string;
  updated_at: string;
}

export interface CollectionItemList {
  items: CollectionItem[];
  total: number;
  limit: number;
  offset: number;
  pagination: PaginationMeta;
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

/** Standardized error shape for apiGet/apiPost/apiPatch/apiDelete below -
 * `message` (inherited from Error), plus `status` (the HTTP status, or 0 for
 * a network/timeout failure that never got a response) and `details` (the
 * parsed response body, if any - e.g. a FastAPI 422's full validation error
 * list, not just its top-level `detail` string). */
export class ApiError extends Error {
  status: number;
  details: unknown;

  constructor(message: string, status: number, details: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

export class ApiTimeoutError extends ApiError {
  constructor(path: string, timeoutMs: number) {
    super(`Request to ${path} timed out after ${timeoutMs}ms`, 0, null);
    this.name = "ApiTimeoutError";
  }
}

/** Parses a FastAPI-style {detail: "..."} error body when present, so
 * validation/conflict errors (missing name, duplicate name, bad color, ...)
 * surface their actual message instead of a generic status-code string. */
async function _errorFromResponse(res: Response, path: string): Promise<ApiError> {
  const details = await res
    .json()
    .catch(() => null as { detail?: string } | null);
  return new ApiError(
    details?.detail || `Request to ${path} failed with status ${res.status}`,
    res.status,
    details,
  );
}

/** Reads a response body defensively: empty body (e.g. a 204/DELETE) -
 * returns undefined rather than letting `res.json()` throw on empty input;
 * a non-empty-but-unparseable body - throws an ApiError instead of letting
 * a raw SyntaxError escape. */
async function _readJsonBody<T>(res: Response, path: string): Promise<T> {
  const text = await res.text();
  if (text.length === 0) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(`Invalid JSON response from ${path}`, res.status, text.slice(0, 500));
  }
}

function buildQueryString(
  params?: Record<string, string | number | boolean | null | undefined>,
): string {
  if (!params) return "";
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue;
    query.set(key, String(value));
  }
  const qs = query.toString();
  return qs ? `?${qs}` : "";
}

export interface ApiRequestOptions {
  /** Query params - null/undefined values are omitted, everything else is
   * stringified (so booleans/numbers don't need manual String() calls). */
  params?: Record<string, string | number | boolean | null | undefined>;
  /** Defaults to ADMIN_FETCH_TIMEOUT_MS (15s). */
  timeoutMs?: number;
}

async function _apiRequest<T>(
  method: string,
  path: string,
  options?: ApiRequestOptions & { body?: unknown },
): Promise<T> {
  const qs = buildQueryString(options?.params);
  const timeoutMs = options?.timeoutMs ?? ADMIN_FETCH_TIMEOUT_MS;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}${qs}`, {
      method,
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
      throw new ApiTimeoutError(path, timeoutMs);
    }
    throw new ApiError(err instanceof Error ? err.message : "Network error", 0, null);
  } finally {
    clearTimeout(timeout);
  }

  if (res.status === 401) throw new AdminAuthRequiredError();
  if (!res.ok) throw await _errorFromResponse(res, path);
  return _readJsonBody<T>(res, path);
}

/** Generic GET against the API (adds the stored admin token if one is set -
 * see adminHeaders() - but still works unauthenticated for public routes).
 * Supports query params and a per-call timeout override; throws
 * AdminAuthRequiredError on 401 and ApiError (message/status/details) for
 * every other failure, including a timeout (as ApiTimeoutError). */
export function apiGet<T>(path: string, options?: ApiRequestOptions): Promise<T> {
  return _apiRequest<T>("GET", path, options);
}

export function apiPost<T>(
  path: string,
  body?: unknown,
  options?: ApiRequestOptions,
): Promise<T> {
  return _apiRequest<T>("POST", path, { ...options, body });
}

export function apiPatch<T>(
  path: string,
  body: unknown,
  options?: ApiRequestOptions,
): Promise<T> {
  return _apiRequest<T>("PATCH", path, { ...options, body });
}

/** T defaults to void since most DELETE endpoints return 204 No Content -
 * pass an explicit T for the handful that return the updated parent
 * resource instead (mirrors authedDeleteReturning below). */
export function apiDelete<T = void>(path: string, options?: ApiRequestOptions): Promise<T> {
  return _apiRequest<T>("DELETE", path, options);
}


// --- Per-user (signed-in) requests --------------------------------------
//
// /collection, /grading, and /collector are gated by a real user session
// (Google login via NextAuth), not the admin token. NextAuth mints a
// short-lived bearer token in its session callback (see src/lib/auth.ts) -
// these helpers fetch the current session client-side and attach it as
// Authorization: Bearer, mirroring adminHeaders()/apiGet() above but for
// per-user auth instead of the shared admin secret.

export class AuthRequiredError extends Error {
  constructor() {
    super("Sign-in required");
    this.name = "AuthRequiredError";
  }
}

async function authedHeaders(): Promise<Record<string, string>> {
  const session = await getSession();
  return session?.apiToken ? { Authorization: `Bearer ${session.apiToken}` } : {};
}

async function authedGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    headers: await authedHeaders(),
  });
  if (res.status === 401) throw new AuthRequiredError();
  if (!res.ok) throw await _errorFromResponse(res, path);
  return res.json() as Promise<T>;
}

async function authedPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: {
      ...(await authedHeaders()),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) throw new AuthRequiredError();
  if (!res.ok) throw await _errorFromResponse(res, path);
  return res.json() as Promise<T>;
}

async function authedPatch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "PATCH",
    headers: { ...(await authedHeaders()), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 401) throw new AuthRequiredError();
  if (!res.ok) throw await _errorFromResponse(res, path);
  return res.json() as Promise<T>;
}

async function authedDelete(path: string): Promise<void> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "DELETE",
    headers: await authedHeaders(),
  });
  if (res.status === 401) throw new AuthRequiredError();
  if (!res.ok) throw await _errorFromResponse(res, path);
}

/** Like authedDelete, but for unassign-style endpoints that return the
 * updated parent resource instead of 204 No Content. */
async function authedDeleteReturning<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "DELETE",
    headers: await authedHeaders(),
  });
  if (res.status === 401) throw new AuthRequiredError();
  if (!res.ok) throw await _errorFromResponse(res, path);
  return res.json() as Promise<T>;
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

export interface MatchExplanation {
  positive: string[];
  negative: string[];
  caps_applied: string[];
}

export interface CandidateMatch {
  card_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  set_code: string;
  rarity: string;
  variant: string | null;
  score: number;
  confidence_label: string;
  ambiguous: boolean;
  explanation: MatchExplanation;
}

export interface CandidateMatches {
  candidate: SnkrdunkCandidate;
  matches: CandidateMatch[];
}

export interface RematchAllResult {
  would_update: number;
  updated: number;
  suggested: number;
  ambiguous: number;
  unmatched: number;
  dry_run: boolean;
}

/* The matching-review workflow below goes through the Next.js server proxy
 * (see src/app/api/admin/snkrdunk-candidates/[id]/matches|rematch|
 * approve-match|reject-match/route.ts and .../rematch-all/route.ts) rather
 * than NEXT_PUBLIC_API_URL, same reasoning as fetchCardAudit above - it's
 * the newer admin-endpoint convention in this codebase. */
export function fetchCandidateMatches(
  candidateId: number,
): Promise<CandidateMatches> {
  return fetchAdminJson<CandidateMatches>(
    `/api/admin/snkrdunk-candidates/${candidateId}/matches`,
  );
}

export function rematchCandidate(
  candidateId: number,
): Promise<CandidateMatches> {
  return fetchAdminJson<CandidateMatches>(
    `/api/admin/snkrdunk-candidates/${candidateId}/rematch`,
    { method: "POST" },
  );
}

export function rematchAllCandidates(params: {
  status?: string;
  limit?: number;
  dry_run: boolean;
}): Promise<RematchAllResult> {
  return fetchAdminJson<RematchAllResult>(
    "/api/admin/snkrdunk-candidates/rematch-all",
    { method: "POST", body: params },
  );
}

export function approveCandidateMatch(
  candidateId: number,
  cardId: number,
  reviewNotes?: string,
): Promise<SnkrdunkCandidate> {
  return fetchAdminJson<SnkrdunkCandidate>(
    `/api/admin/snkrdunk-candidates/${candidateId}/approve-match`,
    { method: "POST", body: { card_id: cardId, review_notes: reviewNotes ?? null } },
  );
}

export function rejectCandidateMatch(
  candidateId: number,
  reviewNotes?: string,
): Promise<SnkrdunkCandidate> {
  return fetchAdminJson<SnkrdunkCandidate>(
    `/api/admin/snkrdunk-candidates/${candidateId}/reject-match`,
    { method: "POST", body: { review_notes: reviewNotes ?? null } },
  );
}

export interface MappingQualityItem {
  mapping_id: number;
  source_name: string | null;
  source_url: string | null;
  source_card_id: string;
  card_id: number;
  card_code: string | null;
  name_en: string | null;
  name_jp: string | null;
  set_code: string | null;
  rarity: string | null;
  variant: string | null;
  is_active: boolean;
  manual_verified: boolean;
  review_status: string;
  match_confidence: number | null;
  match_confidence_label: string;
  risk_level: string;
  issue_types: string[];
  explanation: MatchExplanation;
  latest_price_observed_at: string | null;
  last_match_checked_at: string | null;
}

export interface MappingQualitySummary {
  total_mappings: number;
  ok_count: number;
  review_count: number;
  warning_count: number;
  critical_count: number;
  low_confidence_count: number;
  duplicate_source_url_count: number;
  stale_mapping_count: number;
  unverified_count: number;
  inactive_with_recent_price_count: number;
  active_without_recent_price_count: number;
}

export interface MappingQualityList {
  summary: MappingQualitySummary;
  items: MappingQualityItem[];
  pagination: PaginationMeta;
}

export interface RecheckQualitySummary {
  selected: number;
  would_update: number;
  updated: number;
  ok: number;
  review: number;
  warning: number;
  critical: number;
}

export interface RecheckQualityResult {
  dry_run: boolean;
  summary: RecheckQualitySummary;
  preview: MappingQualityItem[];
}

export type BulkMappingAction =
  | "approve"
  | "reject"
  | "deactivate"
  | "activate"
  | "mark_verified"
  | "mark_pending";

export interface BulkMappingUpdateResult {
  mapping_id: number;
  ok: boolean;
  error: string | null;
}

export interface BulkMappingUpdateResponse {
  action: string;
  results: BulkMappingUpdateResult[];
}

export interface SuggestedCardsForMapping {
  mapping_id: number;
  matches: CandidateMatch[];
}

/* Source mapping quality review goes through the Next.js server proxy (see
 * src/app/api/admin/source-mappings/quality|recheck-quality|bulk-update/
 * route.ts and .../[id]/replace-card|suggested-cards/route.ts), same
 * reasoning as the SNKRDUNK matching fetchers above. */
export function fetchMappingQuality(params?: {
  source?: string;
  review_status?: string;
  is_active?: boolean;
  manual_verified?: boolean;
  confidence_label?: string;
  risk_level?: string;
  issue_type?: string;
  q?: string;
  limit?: number;
  offset?: number;
}): Promise<MappingQualityList> {
  const query = new URLSearchParams();
  if (params?.source) query.set("source", params.source);
  if (params?.review_status) query.set("review_status", params.review_status);
  if (params?.is_active !== undefined) query.set("is_active", String(params.is_active));
  if (params?.manual_verified !== undefined)
    query.set("manual_verified", String(params.manual_verified));
  if (params?.confidence_label) query.set("confidence_label", params.confidence_label);
  if (params?.risk_level) query.set("risk_level", params.risk_level);
  if (params?.issue_type) query.set("issue_type", params.issue_type);
  if (params?.q) query.set("q", params.q);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return fetchAdminJson<MappingQualityList>(
    `/api/admin/source-mappings/quality${qs ? `?${qs}` : ""}`,
  );
}

export function recheckMappingQuality(params: {
  source?: string;
  review_status?: string;
  is_active?: boolean;
  manual_verified?: boolean;
  limit?: number;
  dry_run: boolean;
}): Promise<RecheckQualityResult> {
  return fetchAdminJson<RecheckQualityResult>(
    "/api/admin/source-mappings/recheck-quality",
    { method: "POST", body: params },
  );
}

export function bulkUpdateMappings(
  mappingIds: number[],
  action: BulkMappingAction,
  reviewNotes?: string,
): Promise<BulkMappingUpdateResponse> {
  return fetchAdminJson<BulkMappingUpdateResponse>(
    "/api/admin/source-mappings/bulk-update",
    {
      method: "POST",
      body: { mapping_ids: mappingIds, action, review_notes: reviewNotes ?? null },
    },
  );
}

export function replaceMappingCard(
  mappingId: number,
  cardId: number,
  reviewNotes?: string,
  approve?: boolean,
): Promise<MappingQualityItem> {
  return fetchAdminJson<MappingQualityItem>(
    `/api/admin/source-mappings/${mappingId}/replace-card`,
    {
      method: "POST",
      body: { card_id: cardId, review_notes: reviewNotes ?? null, approve: approve ?? false },
    },
  );
}

export function fetchSuggestedCardsForMapping(
  mappingId: number,
): Promise<SuggestedCardsForMapping> {
  return fetchAdminJson<SuggestedCardsForMapping>(
    `/api/admin/source-mappings/${mappingId}/suggested-cards`,
  );
}

/* Card identity merge / duplicate review - goes through the Next.js server
 * proxy (see src/app/api/admin/cards/duplicates|merge/route.ts and
 * .../[id]/merge-preview/route.ts), same reasoning as the source mapping
 * quality fetchers above. */

export interface DuplicateCardSummary {
  id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  set_code: string;
  rarity: string;
  variant: string | null;
  language: string;
  is_active: boolean;
  merged_into_card_id: number | null;
}

export interface DuplicatePair {
  source_card: DuplicateCardSummary;
  target_card: DuplicateCardSummary;
  score: number;
  confidence_label: string;
  explanation: MatchExplanation;
  recommended_target_card_id: number;
  warnings: string[];
}

export interface DuplicateSummary {
  total_pairs: number;
  exact_duplicate_count: number;
  likely_duplicate_count: number;
  possible_duplicate_count: number;
  weak_match_count: number;
  inactive_merged_cards: number;
}

export interface DuplicateList {
  summary: DuplicateSummary;
  pairs: DuplicatePair[];
  pagination: PaginationMeta;
}

export interface FieldMergePreviewEntry {
  source: unknown;
  target: unknown;
  result: unknown;
  action: string;
}

export interface CardMergePreview {
  source_card: DuplicateCardSummary;
  target_card: DuplicateCardSummary;
  duplicate_score: number;
  confidence_label: string;
  explanation: MatchExplanation;
  field_merge_preview: Record<string, FieldMergePreviewEntry>;
  affected_records: Record<string, number>;
  warnings: string[];
}

export interface CardMergeResult {
  dry_run: boolean;
  merged: boolean;
  source_card_id: number;
  target_card_id: number;
  affected_records: Record<string, number>;
  field_changes: Record<string, unknown>;
  warnings: string[];
  duplicate_score: number;
  confidence_label: string;
}

export type CardMergeFieldStrategy =
  | "keep_target"
  | "fill_missing_target_fields"
  | "overwrite_target_empty_or_shorter_text";

export function fetchCardDuplicates(params?: {
  q?: string;
  set_code?: string;
  rarity?: string;
  variant?: string;
  language?: string;
  confidence_label?: string;
  min_score?: number;
  include_inactive?: boolean;
  limit?: number;
  offset?: number;
}): Promise<DuplicateList> {
  const query = new URLSearchParams();
  if (params?.q) query.set("q", params.q);
  if (params?.set_code) query.set("set_code", params.set_code);
  if (params?.rarity) query.set("rarity", params.rarity);
  if (params?.variant) query.set("variant", params.variant);
  if (params?.language) query.set("language", params.language);
  if (params?.confidence_label) query.set("confidence_label", params.confidence_label);
  if (params?.min_score !== undefined) query.set("min_score", String(params.min_score));
  if (params?.include_inactive !== undefined)
    query.set("include_inactive", String(params.include_inactive));
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return fetchAdminJson<DuplicateList>(`/api/admin/cards/duplicates${qs ? `?${qs}` : ""}`);
}

export function bulkPreviewCardDuplicates(params: {
  min_score?: number;
  confidence_label?: string | null;
  limit?: number;
}): Promise<{ previews: CardMergePreview[] }> {
  return fetchAdminJson<{ previews: CardMergePreview[] }>(
    "/api/admin/cards/duplicates/bulk-preview",
    { method: "POST", body: params },
  );
}

export function fetchCardMergePreview(
  sourceCardId: number,
  targetCardId: number,
  fieldStrategy?: CardMergeFieldStrategy,
): Promise<CardMergePreview> {
  const query = new URLSearchParams();
  query.set("target_card_id", String(targetCardId));
  if (fieldStrategy) query.set("field_strategy", fieldStrategy);
  return fetchAdminJson<CardMergePreview>(
    `/api/admin/cards/${sourceCardId}/merge-preview?${query.toString()}`,
  );
}

export function mergeCards(params: {
  source_card_id: number;
  target_card_id: number;
  dry_run: boolean;
  merge_notes?: string;
  field_strategy?: CardMergeFieldStrategy;
  approve_low_confidence?: boolean;
}): Promise<CardMergeResult> {
  return fetchAdminJson<CardMergeResult>("/api/admin/cards/merge", {
    method: "POST",
    body: params,
  });
}

// --- Catalog coverage (see GET /admin/catalog-coverage*) --------------------

export interface CatalogCoverageSummary {
  total_cards: number;
  active_cards: number;
  inactive_merged_cards: number;
  sets_count: number;
  cards_with_yuyutei_mapping: number;
  cards_with_snkrdunk_mapping: number;
  cards_without_any_mapping: number;
  cards_with_recent_yuyutei_price: number;
  cards_with_recent_snkrdunk_price: number;
  cards_without_recent_price: number;
  cards_in_collection: number;
  cards_on_wishlist: number;
  cards_with_missing_metadata: number;
  cards_with_duplicate_risk: number;
  cards_with_mapping_quality_risk: number;
  metadata_completion_pct: number;
  mapping_coverage_pct: number;
  recent_price_coverage_pct: number;
}

export interface CatalogCoverageBreakdownItem {
  key: string;
  label: string;
  total_cards: number;
  active_cards: number;
  mapped_cards: number;
  unmapped_cards: number;
  recent_price_cards: number;
  collection_cards: number;
  wishlist_cards: number;
  missing_metadata_cards: number;
  duplicate_risk_cards: number;
  mapping_quality_risk_cards: number;
  mapping_coverage_pct: number;
  recent_price_coverage_pct: number;
  metadata_completion_pct: number;
}

export interface CatalogCoverageGapItem {
  card_id: number;
  card_code: string | null;
  name_en: string | null;
  name_jp: string | null;
  set_code: string | null;
  rarity: string | null;
  variant: string | null;
  language: string | null;
  issue_types: string[];
  severity: string;
  suggested_action: string;
}

export interface CatalogCoverageReport {
  summary: CatalogCoverageSummary;
  coverage_by_set: CatalogCoverageBreakdownItem[];
  coverage_by_rarity: CatalogCoverageBreakdownItem[];
  coverage_by_variant: CatalogCoverageBreakdownItem[];
  coverage_by_language: CatalogCoverageBreakdownItem[];
  metadata_gaps: CatalogCoverageGapItem[];
  mapping_gaps: CatalogCoverageGapItem[];
  price_gaps: CatalogCoverageGapItem[];
  duplicate_risks: CatalogCoverageGapItem[];
  mapping_quality_risks: CatalogCoverageGapItem[];
  // Loosely-typed - see PriceSourceHealthSummary for the real shape (kept
  // as Record here rather than importing that type ordering-wise, since
  // both are declared in this same file - see the type below).
  price_source_health: PriceSourceHealthSummary | null;
}

export type CatalogCoverageGapType = "metadata" | "mapping" | "price" | "duplicate" | "mapping_quality";

export interface CatalogCoverageGapsResponse {
  gap_type: CatalogCoverageGapType;
  items: CatalogCoverageGapItem[];
  pagination: PaginationMeta;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/catalog-coverage/route.ts) - same reasoning as
 * fetchCardAudit. */
export function fetchCatalogCoverage(params?: {
  set_code?: string;
  language?: string;
  variant?: string;
  rarity?: string;
  include_inactive?: boolean;
}): Promise<CatalogCoverageReport> {
  const query = new URLSearchParams();
  if (params?.set_code) query.set("set_code", params.set_code);
  if (params?.language) query.set("language", params.language);
  if (params?.variant) query.set("variant", params.variant);
  if (params?.rarity) query.set("rarity", params.rarity);
  if (params?.include_inactive !== undefined) {
    query.set("include_inactive", String(params.include_inactive));
  }
  const qs = query.toString();
  return fetchAdminJson<CatalogCoverageReport>(`/api/admin/catalog-coverage${qs ? `?${qs}` : ""}`);
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/catalog-coverage/gaps/route.ts). */
export function fetchCatalogCoverageGaps(params: {
  gap_type: CatalogCoverageGapType;
  set_code?: string;
  rarity?: string;
  variant?: string;
  language?: string;
  severity?: string;
  limit?: number;
  offset?: number;
}): Promise<CatalogCoverageGapsResponse> {
  const query = new URLSearchParams();
  query.set("gap_type", params.gap_type);
  if (params.set_code) query.set("set_code", params.set_code);
  if (params.rarity) query.set("rarity", params.rarity);
  if (params.variant) query.set("variant", params.variant);
  if (params.language) query.set("language", params.language);
  if (params.severity) query.set("severity", params.severity);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  return fetchAdminJson<CatalogCoverageGapsResponse>(
    `/api/admin/catalog-coverage/gaps?${query.toString()}`,
  );
}

// --- Price source health (see GET /admin/price-source-health*) -------------

export interface PriceSourceHealthSummary {
  sources_count: number;
  active_sources_count: number;
  total_active_mappings: number;
  mappings_with_recent_price: number;
  mappings_without_recent_price: number;
  stale_price_count: number;
  missing_price_count: number;
  last_successful_refresh_at: string | null;
  last_failed_refresh_at: string | null;
  recent_refresh_success_rate_pct: number;
  blocked_source_count: number;
  error_source_count: number;
}

export interface SourceHealthItem {
  source_id: number;
  source_name: string;
  active_mapping_count: number;
  recent_price_count: number;
  stale_price_count: number;
  missing_price_count: number;
  latest_price_observed_at: string | null;
  latest_refresh_status: string | null;
  latest_refresh_started_at: string | null;
  latest_refresh_finished_at: string | null;
  recent_refresh_success_rate_pct: number;
  average_refresh_duration_seconds: number | null;
  blocked_count_7d: number;
  error_count_7d: number;
  health_status: string;
  warnings: string[];
}

export interface HealthCoverageBreakdownItem {
  key: string;
  label: string;
  mapped_cards: number;
  recent_price_cards: number;
  stale_price_cards: number;
  missing_price_cards: number;
  coverage_pct: number;
}

export interface PriceGapItem {
  mapping_id: number;
  card_id: number;
  card_code: string | null;
  name_en: string | null;
  set_code: string | null;
  rarity: string | null;
  variant: string | null;
  language: string | null;
  source_name: string;
  source_url: string | null;
  latest_price_observed_at: string | null;
  latest_price_type: string | null;
  latest_price_jpy: number | null;
  issue_type: string;
  severity: string;
  suggested_action: string;
}

export interface RefreshRunSummaryItem {
  id: number;
  status: string;
  source_filter: string | null;
  started_at: string;
  finished_at: string | null;
  dry_run: boolean;
  mappings_checked: number;
  mappings_failed: number;
  error_message: string | null;
}

export interface PriceSourceHealthReport {
  summary: PriceSourceHealthSummary;
  sources: SourceHealthItem[];
  coverage_by_set: HealthCoverageBreakdownItem[];
  coverage_by_rarity: HealthCoverageBreakdownItem[];
  stale_prices: PriceGapItem[];
  missing_prices: PriceGapItem[];
  refresh_runs: RefreshRunSummaryItem[];
  warnings: string[];
}

export type PriceSourceHealthGapType = "stale" | "missing" | "failed_refresh" | "blocked" | "low_coverage";

export interface PriceSourceHealthGapsResponse {
  gap_type: PriceSourceHealthGapType;
  items: PriceGapItem[];
  pagination: PaginationMeta;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/price-source-health/route.ts) - same reasoning as
 * fetchCatalogCoverage. */
export function fetchPriceSourceHealth(params?: {
  source?: string;
  set_code?: string;
  rarity?: string;
  variant?: string;
  language?: string;
  include_inactive_mappings?: boolean;
}): Promise<PriceSourceHealthReport> {
  const query = new URLSearchParams();
  if (params?.source) query.set("source", params.source);
  if (params?.set_code) query.set("set_code", params.set_code);
  if (params?.rarity) query.set("rarity", params.rarity);
  if (params?.variant) query.set("variant", params.variant);
  if (params?.language) query.set("language", params.language);
  if (params?.include_inactive_mappings !== undefined) {
    query.set("include_inactive_mappings", String(params.include_inactive_mappings));
  }
  const qs = query.toString();
  return fetchAdminJson<PriceSourceHealthReport>(`/api/admin/price-source-health${qs ? `?${qs}` : ""}`);
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/price-source-health/gaps/route.ts). */
export function fetchPriceSourceHealthGaps(params: {
  gap_type: PriceSourceHealthGapType;
  source?: string;
  set_code?: string;
  rarity?: string;
  limit?: number;
  offset?: number;
}): Promise<PriceSourceHealthGapsResponse> {
  const query = new URLSearchParams();
  query.set("gap_type", params.gap_type);
  if (params.source) query.set("source", params.source);
  if (params.set_code) query.set("set_code", params.set_code);
  if (params.rarity) query.set("rarity", params.rarity);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  return fetchAdminJson<PriceSourceHealthGapsResponse>(
    `/api/admin/price-source-health/gaps?${query.toString()}`,
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
  return authedGet<CollectionItemList>(`/collection${qs ? `?${qs}` : ""}`);
}

export function fetchCollectionSummary(): Promise<CollectionSummary> {
  return authedGet<CollectionSummary>("/collection/summary");
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

export type ValuationMode = "raw_market" | "graded_adjusted";

export type GradedAdjustedBasis = "graded_value" | "snkrdunk_floor" | "yuyutei_sell";

export interface GradedAdjustedValuation {
  value_jpy: number | null;
  basis: GradedAdjustedBasis | null;
  grading_submission_id: number | null;
  grading_company: string | null;
  final_grade: string | null;
  graded_value_jpy: number | null;
  raw_fallback_basis: GradedAdjustedBasis | null;
  pnl_jpy: number | null;
  pnl_pct: number | null;
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
  tags: CollectorTag[];
  groups: CollectorGroup[];
  grading: GradingInfo;
  graded_adjusted: GradedAdjustedValuation;
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
  valuation_mode: ValuationMode;
  graded_adjusted_value_jpy: number;
  pnl_vs_graded_adjusted_jpy: number;
  pnl_vs_graded_adjusted_pct: number;
  items_using_graded_value: number;
  items_using_raw_fallback: number;
  items_missing_graded_adjusted_value: number;
}

export interface PortfolioValuation {
  summary: PortfolioValuationSummary;
  items: PortfolioValuationItem[];
}

export function fetchCollectionValuation(
  valuationMode: ValuationMode = "raw_market",
): Promise<PortfolioValuation> {
  const query = new URLSearchParams({ valuation_mode: valuationMode });
  return authedGet<PortfolioValuation>(`/collection/valuation?${query.toString()}`);
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
  graded_adjusted_value_jpy: number | null;
  pnl_vs_graded_adjusted_jpy: number | null;
  items_using_graded_value: number | null;
  items_using_raw_fallback: number | null;
  items_missing_graded_adjusted_value: number | null;
}

export function fetchCollectionValuationHistory(
  days: string,
): Promise<PortfolioValuationSnapshot[]> {
  const query = new URLSearchParams({ days });
  return authedGet<PortfolioValuationSnapshot[]>(
    `/collection/valuation/history?${query.toString()}`,
  );
}

// --- Collection analytics (see GET /analytics/collection) -----------------

export interface CollectionAnalyticsSummary {
  total_items: number;
  total_quantity: number;
  total_cost_basis_jpy: number;
  raw_market_floor_value_jpy: number;
  graded_adjusted_value_jpy: number;
  unrealized_pnl_jpy: number;
  unrealized_pnl_pct: number;
  items_missing_cost_basis: number;
  items_missing_market_price: number;
  owned_unique_cards: number;
  wishlist_unique_cards: number;
  grading_active_count: number;
}

export interface CollectionAnalyticsBreakdownItem {
  key: string;
  label: string;
  item_count: number;
  quantity: number;
  cost_basis_jpy: number;
  value_jpy: number;
  pnl_jpy: number;
  pnl_pct: number | null;
  portfolio_weight_pct: number;
}

export interface CollectionAnalyticsBreakdowns {
  by_set: CollectionAnalyticsBreakdownItem[];
  by_rarity: CollectionAnalyticsBreakdownItem[];
  by_variant: CollectionAnalyticsBreakdownItem[];
  by_language: CollectionAnalyticsBreakdownItem[];
  by_status: CollectionAnalyticsBreakdownItem[];
  by_tag: CollectionAnalyticsBreakdownItem[];
  by_group: CollectionAnalyticsBreakdownItem[];
  by_grading_status: CollectionAnalyticsBreakdownItem[];
}

export interface CollectionAnalyticsTopCard {
  collection_item_id: number;
  card_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  set_code: string;
  rarity: string;
  quantity: number;
  value_jpy: number;
  portfolio_weight_pct: number;
}

export interface CollectionAnalyticsConcentration {
  top_5_cards_by_value: CollectionAnalyticsTopCard[];
  top_10_cards_value_pct: number;
  largest_single_card_value_pct: number;
  largest_set_exposure: CollectionAnalyticsBreakdownItem | null;
  largest_rarity_exposure: CollectionAnalyticsBreakdownItem | null;
}

export interface CollectionAnalyticsHighestCostBasisItem {
  collection_item_id: number;
  card_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  purchase_price_jpy: number | null;
  quantity: number;
  cost_basis_jpy: number;
  status: string;
}

export interface CollectionAnalyticsCostBasis {
  items_with_cost_basis: number;
  items_without_cost_basis: number;
  average_cost_basis_jpy: number;
  median_cost_basis_jpy: number;
  highest_cost_basis_items: CollectionAnalyticsHighestCostBasisItem[];
}

export interface CollectionAnalyticsValuationQuality {
  items_with_yuyutei_sell: number;
  items_with_yuyutei_buy: number;
  items_with_snkrdunk_floor: number;
  items_using_graded_value: number;
  items_using_raw_fallback: number;
  coverage_pct: number;
}

export interface CollectionAnalytics {
  summary: CollectionAnalyticsSummary;
  breakdowns: CollectionAnalyticsBreakdowns;
  concentration: CollectionAnalyticsConcentration;
  cost_basis: CollectionAnalyticsCostBasis;
  valuation_quality: CollectionAnalyticsValuationQuality;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/analytics/collection/route.ts) rather than NEXT_PUBLIC_API_URL,
 * same rationale as fetchDashboardOverview/fetchMarketOpportunities -
 * browser-side fetches to the backend's host port are unreliable in
 * Codespaces/forwarded-port environments, and this endpoint also needs the
 * signed-in user's session forwarded server-side. */
export function fetchCollectionAnalytics(params?: {
  valuation_mode?: ValuationMode;
  include_sold?: boolean;
}): Promise<CollectionAnalytics> {
  const query = new URLSearchParams();
  if (params?.valuation_mode) query.set("valuation_mode", params.valuation_mode);
  if (params?.include_sold !== undefined) {
    query.set("include_sold", String(params.include_sold));
  }
  const qs = query.toString();
  return fetchAdminJson<CollectionAnalytics>(`/api/analytics/collection${qs ? `?${qs}` : ""}`);
}

export function createCollectionItem(
  body: CollectionItemInput,
): Promise<CollectionItem> {
  return authedPost<CollectionItem>("/collection", body);
}

export function updateCollectionItem(
  itemId: number,
  body: Partial<CollectionItemInput>,
): Promise<CollectionItem> {
  return authedPatch<CollectionItem>(`/collection/${itemId}`, body);
}

export function deleteCollectionItem(itemId: number): Promise<void> {
  return authedDelete(`/collection/${itemId}`);
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

/** Same as importCollectionCsv above, but background=true - the backend
 * returns 202 immediately with a file_job_id instead of the full import
 * result; poll fetchFileJob(file_job_id) for progress/status/errors. */
export async function importCollectionCsvBackground(
  file: File,
  params: { dryRun: boolean; mode: CollectionImportMode },
): Promise<FileJobCreated> {
  const query = new URLSearchParams({
    dry_run: String(params.dryRun),
    mode: params.mode,
    background: "true",
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
    .catch(() => null as (Partial<FileJobCreated> & { error?: string; detail?: string }) | null);

  if (!res.ok || !details) {
    throw new Error(
      details?.error || details?.detail || `Import failed with status ${res.status}`,
    );
  }

  return details as FileJobCreated;
}

/** Creates a background collection export job - poll fetchFileJob(id) and
 * downloadFileJob(id) once status=success. Routed through the Next.js
 * server proxy (see src/app/api/collection/export/job/route.ts). */
export async function createCollectionExportJob(): Promise<FileJobCreated> {
  return fetchAdminJson<FileJobCreated>("/api/collection/export/job", {
    method: "POST",
    body: {},
  });
}

// --- File jobs (background import/export - see 'Large import/export jobs'
// in docs/operations.md) ----------------------------------------------

export const FILE_JOB_TYPES = [
  "collection_import",
  "wishlist_import",
  "collection_export",
  "wishlist_export",
  "backup_export",
  "backup_validate",
  "backup_restore",
] as const;
export type FileJobType = (typeof FILE_JOB_TYPES)[number];

export const FILE_JOB_STATUSES = ["queued", "running", "success", "failed", "cancelled"] as const;
export type FileJobStatus = (typeof FILE_JOB_STATUSES)[number];

export interface FileJobCreated {
  file_job_id: number;
  status: string;
}

export interface FileJob {
  id: number;
  job_type: FileJobType;
  status: FileJobStatus;
  original_filename: string | null;
  output_filename: string | null;
  content_type: string | null;
  dry_run: boolean;
  mode: string | null;
  progress_current: number;
  progress_total: number | null;
  download_ready: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  summary: Record<string, any> | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  errors: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  warnings: any;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface FileJobListResponse {
  jobs: FileJob[];
  total: number;
  limit: number;
  offset: number;
  pagination: PaginationMeta;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/file-jobs/route.ts) - accepts either a signed-in user's
 * session or an X-Admin-Token, see app.auth.file_job_access. */
export function fetchFileJobs(params?: {
  job_type?: string;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<FileJobListResponse> {
  const query = new URLSearchParams();
  if (params?.job_type) query.set("job_type", params.job_type);
  if (params?.status) query.set("status", params.status);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return fetchAdminJson<FileJobListResponse>(`/api/file-jobs${qs ? `?${qs}` : ""}`);
}

/** Routed through the Next.js server proxy (see
 * src/app/api/file-jobs/[id]/route.ts). */
export function fetchFileJob(fileJobId: number): Promise<FileJob> {
  return fetchAdminJson<FileJob>(`/api/file-jobs/${fileJobId}`);
}

/** Downloads a completed file job's output through the Next.js proxy (see
 * src/app/api/file-jobs/[id]/download/route.ts) and triggers a browser file
 * download, using the filename the backend set via Content-Disposition. */
export async function downloadFileJob(fileJobId: number): Promise<void> {
  const res = await fetch(`/api/file-jobs/${fileJobId}/download`, {
    headers: adminHeaders(),
    cache: "no-store",
  });

  if (!res.ok) {
    const details = await res
      .json()
      .catch(() => null as { error?: string; detail?: string } | null);
    throw new Error(
      details?.error || details?.detail || `Download failed with status ${res.status}`,
    );
  }

  const blob = await res.blob();
  const filename =
    filenameFromContentDisposition(res.headers.get("content-disposition")) ||
    `file_job_${fileJobId}`;

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/** Routed through the Next.js server proxy (see
 * src/app/api/file-jobs/[id]/cancel/route.ts). */
export function cancelFileJob(fileJobId: number): Promise<{ id: number; status: string }> {
  return fetchAdminJson<{ id: number; status: string }>(`/api/file-jobs/${fileJobId}/cancel`, {
    method: "POST",
  });
}

export interface FileJobCleanupResult {
  dry_run: boolean;
  older_than_days: number;
  would_delete: number;
  deleted: number;
}

/** Admin-only - routed through the Next.js server proxy (see
 * src/app/api/admin/file-jobs/cleanup/route.ts). */
export function cleanupFileJobs(body: {
  older_than_days: number;
  dry_run: boolean;
  confirm?: string | null;
}): Promise<FileJobCleanupResult> {
  return fetchAdminJson<FileJobCleanupResult>("/api/admin/file-jobs/cleanup", {
    method: "POST",
    body,
  });
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
  limit: number;
  offset: number;
  pagination: PaginationMeta;
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
  limit: number;
  offset: number;
  pagination: PaginationMeta;
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
  tags: CollectorTag[];
  groups: CollectorGroup[];
  grading: GradingInfo;
  wishlist_item_id: number | null;
  wishlist_priority: string | null;
  wishlist_target_buy_price_jpy: number | null;
  wishlist_target_hit: boolean;
}

export interface MarketOpportunitiesSummary {
  total_opportunities: number;
  average_score: number;
  highest_score: number;
  by_category: Record<string, number>;
  wishlist_target_hit_count: number;
}

export interface MarketOpportunitiesResponse {
  summary: MarketOpportunitiesSummary;
  opportunities: MarketOpportunity[];
  limit: number;
  offset: number;
  pagination: PaginationMeta;
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

// --- Admin card catalog (see GET/POST /admin/cards*) ------------------------

export interface AdminCard {
  id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  set_code: string;
  rarity: string;
  variant: string | null;
  language: string;
  image_url: string | null;
  release_date: string | null;
  artist: string | null;
  character: string | null;
  color: string | null;
  card_type: string | null;
  cost: number | null;
  power: number | null;
  counter: number | null;
  attribute: string | null;
  effect_text: string | null;
  trigger_text: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminCardListSummary {
  total_cards: number;
  missing_metadata_count: number;
  by_set: Record<string, number>;
  by_rarity: Record<string, number>;
}

export interface AdminCardListResponse {
  summary: AdminCardListSummary;
  cards: AdminCard[];
  pagination: PaginationMeta;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/cards/route.ts). */
export function fetchAdminCards(params?: {
  q?: string;
  set_code?: string;
  rarity?: string;
  variant?: string;
  language?: string;
  missing_metadata?: boolean;
  limit?: number;
  offset?: number;
}): Promise<AdminCardListResponse> {
  const query = new URLSearchParams();
  if (params?.q) query.set("q", params.q);
  if (params?.set_code) query.set("set_code", params.set_code);
  if (params?.rarity) query.set("rarity", params.rarity);
  if (params?.variant) query.set("variant", params.variant);
  if (params?.language) query.set("language", params.language);
  if (params?.missing_metadata !== undefined) {
    query.set("missing_metadata", String(params.missing_metadata));
  }
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return fetchAdminJson<AdminCardListResponse>(`/api/admin/cards${qs ? `?${qs}` : ""}`);
}

export interface CardCatalogImportRowError {
  row_number: number;
  card_code: string | null;
  error: string;
}

export interface CardCatalogFieldChange {
  old: unknown;
  new: unknown;
}

export interface CardCatalogImportPreviewItem {
  row_number: number;
  card_code: string;
  action: string;
  changes: Record<string, CardCatalogFieldChange>;
}

export interface CardCatalogImportSummary {
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  created: number;
  updated: number;
  skipped: number;
}

export interface CardCatalogImportResponse {
  dry_run: boolean;
  overwrite: boolean;
  summary: CardCatalogImportSummary;
  errors: CardCatalogImportRowError[];
  preview: CardCatalogImportPreviewItem[];
}

/** Uploads a card catalog CSV through the Next.js proxy (see
 * src/app/api/admin/cards/import/route.ts). */
export async function importCardsCsv(
  file: File,
  params: { dryRun: boolean; overwrite: boolean },
): Promise<CardCatalogImportResponse> {
  const query = new URLSearchParams({
    dry_run: String(params.dryRun),
    overwrite: String(params.overwrite),
  });

  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`/api/admin/cards/import?${query.toString()}`, {
    method: "POST",
    headers: adminHeaders(),
    body: formData,
  });

  const details = await res
    .json()
    .catch(
      () => null as (Partial<CardCatalogImportResponse> & { error?: string; detail?: string }) | null,
    );

  if (!res.ok || !details) {
    throw new Error(details?.error || details?.detail || `Import failed with status ${res.status}`);
  }

  return details as CardCatalogImportResponse;
}

/** Downloads /admin/cards/export.csv through the Next.js proxy (see
 * src/app/api/admin/cards/export/route.ts) and triggers a browser file
 * download, using the filename the backend set via Content-Disposition. */
export async function downloadCardsCsv(): Promise<void> {
  const res = await fetch("/api/admin/cards/export", {
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
    filenameFromContentDisposition(res.headers.get("content-disposition")) || "cards_export.csv";

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export interface SystemCheckResult {
  name: string;
  status: "pass" | "warning" | "fail";
  severity: "info" | "warning" | "critical";
  message: string;
}

export interface SystemCheckSummary {
  checks_total: number;
  checks_passed: number;
  warnings: number;
  critical: number;
}

export interface CatalogOperationsSummary {
  card_audit_status: string;
  duplicate_risk_count: number;
  mapping_quality_critical_count: number;
  metadata_completion_pct: number;
  mapping_coverage_pct: number;
  recent_price_coverage_pct: number;
  price_source_health_status: string;
  latest_import_validation_status: string;
  warnings: string[];
}

export interface SystemCheckResponse {
  status: "ok" | "warning" | "critical";
  summary: SystemCheckSummary;
  checks: SystemCheckResult[];
  catalog_operations: CatalogOperationsSummary;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/system-check/route.ts) - same reasoning as
 * fetchCardAudit. */
export function fetchSystemCheck(): Promise<SystemCheckResponse> {
  return fetchAdminJson<SystemCheckResponse>("/api/admin/system-check");
}

export interface DbIndexCheck {
  table: string;
  index: string;
  status: "pass" | "warning" | "critical";
  severity: "warning" | "critical";
  message: string;
}

export interface DbIndexAuditSummary {
  total_checks: number;
  passed: number;
  warnings: number;
  critical: number;
}

export interface DbIndexAuditResponse {
  summary: DbIndexAuditSummary;
  checks: DbIndexCheck[];
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/db-index-audit/route.ts) - same reasoning as
 * fetchCardAudit. */
export function fetchDbIndexAudit(): Promise<DbIndexAuditResponse> {
  return fetchAdminJson<DbIndexAuditResponse>("/api/admin/db-index-audit");
}

export interface SlowRequest {
  created_at: string;
  message: string;
  context: Record<string, unknown> | null;
}

export interface LargestResponse {
  created_at: string;
  method: string | null;
  path: string | null;
  size_bytes: number | null;
}

export interface PerformanceSummary {
  status: "ok" | "warning" | "critical";
  database: {
    price_observations_count: number;
    raw_snapshots_count: number;
    market_signal_events_count: number;
    collector_activity_events_count: number;
    app_log_events_count: number;
  };
  latest_slow_requests: SlowRequest[];
  index_audit: {
    warnings: number;
    critical: number;
  };
  response_size_warnings_last_24h: number;
  slow_requests_last_24h: number;
  largest_recent_responses: LargestResponse[];
  cache_enabled: boolean;
  cache_backend: string;
  cache_keys: number | null;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/performance/summary/route.ts) - same reasoning as
 * fetchCardAudit. */
export function fetchPerformanceSummary(): Promise<PerformanceSummary> {
  return fetchAdminJson<PerformanceSummary>("/api/admin/performance/summary");
}

export interface DataRetentionPolicy {
  table: string;
  retention_days: number;
  mode: string;
  protected_records: string;
  enabled: boolean;
}

export interface DataRetentionPolicyResponse {
  policies: DataRetentionPolicy[];
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/data-retention/policy/route.ts) - same reasoning as
 * fetchCardAudit. */
export function fetchDataRetentionPolicy(): Promise<DataRetentionPolicyResponse> {
  return fetchAdminJson<DataRetentionPolicyResponse>("/api/admin/data-retention/policy");
}

export interface DataRetentionPruneRequest {
  dry_run: boolean;
  tables?: string[] | null;
  confirm?: string | null;
}

export interface DataRetentionPruneResult {
  table: string;
  retention_days: number | null;
  rows_would_delete: number;
  rows_deleted: number;
  status: "ok" | "skipped" | "error";
  warning: string | null;
}

export interface DataRetentionPruneResponse {
  dry_run: boolean;
  summary: {
    tables_checked: number;
    total_rows_would_delete: number;
    total_rows_deleted: number;
    warnings: number;
  };
  results: DataRetentionPruneResult[];
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/data-retention/prune/route.ts). */
export function pruneDataRetention(
  body: DataRetentionPruneRequest,
): Promise<DataRetentionPruneResponse> {
  return fetchAdminJson<DataRetentionPruneResponse>("/api/admin/data-retention/prune", {
    method: "POST",
    body,
  });
}

export interface CacheStatus {
  enabled: boolean;
  backend: string;
  stats: {
    keys: number;
    hits: number;
    misses: number;
  };
  ttl: {
    dashboard: number;
    market: number;
    collection: number;
  };
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/cache/status/route.ts). */
export function fetchCacheStatus(): Promise<CacheStatus> {
  return fetchAdminJson<CacheStatus>("/api/admin/cache/status");
}

export interface CacheClearRequest {
  prefix?: string | null;
  confirm: string;
}

export interface CacheClearResponse {
  success: boolean;
  prefix: string | null;
  deleted_count: number | null;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/cache/clear/route.ts). */
export function clearCache(body: CacheClearRequest): Promise<CacheClearResponse> {
  return fetchAdminJson<CacheClearResponse>("/api/admin/cache/clear", {
    method: "POST",
    body,
  });
}

export interface JobLock {
  lock_name: string;
  owner_id: string;
  acquired_at: string;
  expires_at: string;
  status: "active" | "released" | "expired";
  metadata: Record<string, unknown> | null;
}

export interface JobLockListResponse {
  locks: JobLock[];
}

export interface JobLockCleanupResponse {
  cleaned_up_count: number;
}

export interface JobLockForceReleaseResponse {
  released: boolean;
  lock_name: string;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/job-locks/route.ts) - same reasoning as fetchCardAudit. */
export function fetchJobLocks(): Promise<JobLockListResponse> {
  return fetchAdminJson<JobLockListResponse>("/api/admin/job-locks");
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/job-locks/cleanup-expired/route.ts). */
export function cleanupExpiredJobLocks(): Promise<JobLockCleanupResponse> {
  return fetchAdminJson<JobLockCleanupResponse>("/api/admin/job-locks/cleanup-expired", {
    method: "POST",
  });
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/job-locks/[lockName]/force-release/route.ts). confirm
 * must be exactly "RELEASE" or the backend rejects it with a 400. */
export function forceReleaseJobLock(
  lockName: string,
  confirm: string,
): Promise<JobLockForceReleaseResponse> {
  return fetchAdminJson<JobLockForceReleaseResponse>(
    `/api/admin/job-locks/${encodeURIComponent(lockName)}/force-release`,
    { method: "POST", body: { confirm } },
  );
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
  graded_adjusted_value_jpy: number | null;
}

export interface MarketReportOpportunitySummary {
  total_opportunities: number;
  highest_score: number | null;
  average_score: number | null;
  by_category: Record<string, number>;
  wishlist_target_hit_count: number;
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
  pagination: PaginationMeta;
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
  pagination: PaginationMeta;
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
  includeLogs: boolean;
}): Promise<void> {
  const query = new URLSearchParams({
    include_prices: String(params.includePrices),
    include_raw_snapshots: String(params.includeRawSnapshots),
    include_refresh_runs: String(params.includeRefreshRuns),
    include_logs: String(params.includeLogs),
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

/** Creates a background backup export job - poll fetchFileJob(id) and
 * downloadFileJob(id) once status=success. Admin-only - routed through the
 * Next.js server proxy (see src/app/api/admin/backup/export/job/route.ts). */
export function createBackupExportJob(params: {
  includePrices: boolean;
  includeRawSnapshots: boolean;
  includeRefreshRuns: boolean;
  includeLogs: boolean;
}): Promise<FileJobCreated> {
  return fetchAdminJson<FileJobCreated>("/api/admin/backup/export/job", {
    method: "POST",
    body: {
      include_prices: params.includePrices,
      include_raw_snapshots: params.includeRawSnapshots,
      include_refresh_runs: params.includeRefreshRuns,
      include_logs: params.includeLogs,
    },
  });
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

// --- Import templates / validation --------------------------------------

export const IMPORT_TYPES = [
  "card_catalog",
  "source_mappings",
  "snkrdunk_candidates",
  "collection",
  "wishlist",
] as const;
export type ImportType = (typeof IMPORT_TYPES)[number];

export interface ImportTemplate {
  template_type: ImportType;
  filename: string;
  description: string;
  required_columns: string[];
  optional_columns: string[];
  download_url: string;
  notes: string[];
}

export interface ImportTemplateListResponse {
  templates: ImportTemplate[];
}

export interface ImportRowIssue {
  row_number: number;
  field: string | null;
  value: unknown;
  code: string;
  message: string;
}

export interface ImportPreviewRow {
  row_number: number;
  action: "would_create" | "would_update" | "would_skip" | "invalid";
  normalized_values: Record<string, unknown>;
  warnings: string[];
  errors: string[];
}

export interface ImportValidationSummary {
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  warning_rows: number;
  duplicate_rows: number;
  would_create: number;
  would_update: number;
  would_skip: number;
}

export interface ImportValidationColumns {
  required_columns: string[];
  optional_columns: string[];
  received_columns: string[];
  missing_required_columns: string[];
  unknown_columns: string[];
}

export interface ImportValidationResponse {
  import_type: string;
  valid: boolean;
  summary: ImportValidationSummary;
  columns: ImportValidationColumns;
  errors: ImportRowIssue[];
  warnings: ImportRowIssue[];
  preview: ImportPreviewRow[];
}

export interface ImportValidationReport {
  id: number;
  created_at: string;
  import_type: string;
  filename: string | null;
  valid: boolean;
  strict: boolean;
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  warning_rows: number;
  duplicate_rows: number;
}

export interface ImportValidationReportDetail extends ImportValidationReport {
  report_payload_json: ImportValidationResponse;
}

export interface ImportValidationReportListResponse {
  reports: ImportValidationReport[];
  pagination: PaginationMeta;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/import-templates/route.ts). */
export function fetchImportTemplates(): Promise<ImportTemplateListResponse> {
  return fetchAdminJson<ImportTemplateListResponse>("/api/admin/import-templates");
}

/** Downloads /admin/import-templates/{templateType}.csv through the Next.js
 * proxy (see src/app/api/admin/import-templates/[type]/route.ts) and
 * triggers a browser file download, using the filename the backend set via
 * Content-Disposition. */
export async function downloadImportTemplate(templateType: ImportType): Promise<void> {
  const res = await fetch(`/api/admin/import-templates/${templateType}`, {
    headers: adminHeaders(),
    cache: "no-store",
  });

  if (res.status === 401) throw new AdminAuthRequiredError();
  if (!res.ok) {
    const details = await res
      .json()
      .catch(() => null as { error?: string; detail?: string } | null);
    throw new Error(
      details?.error || details?.detail || `Template download failed with status ${res.status}`,
    );
  }

  const blob = await res.blob();
  const filename =
    filenameFromContentDisposition(res.headers.get("content-disposition")) ||
    `${templateType}_template.csv`;

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/import-validation/[type]/route.ts). */
export function validateImportCsv(
  importType: ImportType,
  file: File,
  params: { strict: boolean; maxPreviewRows: number; userId?: number },
): Promise<ImportValidationResponse> {
  const query: Record<string, string> = {
    strict: String(params.strict),
    max_preview_rows: String(params.maxPreviewRows),
  };
  if (params.userId !== undefined) query.user_id = String(params.userId);
  return postBackupFile<ImportValidationResponse>(
    `/api/admin/import-validation/${importType}`,
    file,
    query,
  );
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/import-validation/reports/route.ts). */
export function fetchImportValidationReports(params?: {
  importType?: string;
  valid?: boolean;
  limit?: number;
  offset?: number;
}): Promise<ImportValidationReportListResponse> {
  const query = new URLSearchParams();
  if (params?.importType) query.set("import_type", params.importType);
  if (params?.valid !== undefined) query.set("valid", String(params.valid));
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return fetchAdminJson<ImportValidationReportListResponse>(
    `/api/admin/import-validation/reports${qs ? `?${qs}` : ""}`,
  );
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/import-validation/reports/[id]/route.ts). */
export function fetchImportValidationReport(id: number): Promise<ImportValidationReportDetail> {
  return fetchAdminJson<ImportValidationReportDetail>(`/api/admin/import-validation/reports/${id}`);
}

// --- Collector tags / groups ------------------------------------------

export function fetchCollectorTags(): Promise<CollectorTag[]> {
  return authedGet<CollectorTag[]>("/collector/tags");
}

export function createCollectorTag(body: CollectorTagInput): Promise<CollectorTag> {
  return authedPost<CollectorTag>("/collector/tags", body);
}

export function updateCollectorTag(
  tagId: number,
  body: Partial<CollectorTagInput>,
): Promise<CollectorTag> {
  return authedPatch<CollectorTag>(`/collector/tags/${tagId}`, body);
}

export function deleteCollectorTag(tagId: number): Promise<void> {
  return authedDelete(`/collector/tags/${tagId}`);
}

export function fetchCollectorGroups(): Promise<CollectorGroup[]> {
  return authedGet<CollectorGroup[]>("/collector/groups");
}

export function createCollectorGroup(body: CollectorGroupInput): Promise<CollectorGroup> {
  return authedPost<CollectorGroup>("/collector/groups", body);
}

export function updateCollectorGroup(
  groupId: number,
  body: Partial<CollectorGroupInput>,
): Promise<CollectorGroup> {
  return authedPatch<CollectorGroup>(`/collector/groups/${groupId}`, body);
}

export function deleteCollectorGroup(groupId: number): Promise<void> {
  return authedDelete(`/collector/groups/${groupId}`);
}

export function assignCardTag(cardId: number, tagId: number): Promise<Card> {
  return authedPost<Card>(`/cards/${cardId}/tags/${tagId}`);
}

export function unassignCardTag(cardId: number, tagId: number): Promise<Card> {
  return authedDeleteReturning<Card>(`/cards/${cardId}/tags/${tagId}`);
}

export function assignCollectionItemTag(
  itemId: number,
  tagId: number,
): Promise<CollectionItem> {
  return authedPost<CollectionItem>(`/collection/${itemId}/tags/${tagId}`);
}

export function unassignCollectionItemTag(
  itemId: number,
  tagId: number,
): Promise<CollectionItem> {
  return authedDeleteReturning<CollectionItem>(`/collection/${itemId}/tags/${tagId}`);
}

export function assignCollectionItemGroup(
  itemId: number,
  groupId: number,
): Promise<CollectionItem> {
  return authedPost<CollectionItem>(`/collection/${itemId}/groups/${groupId}`);
}

export function unassignCollectionItemGroup(
  itemId: number,
  groupId: number,
): Promise<CollectionItem> {
  return authedDeleteReturning<CollectionItem>(`/collection/${itemId}/groups/${groupId}`);
}

// --- Grading submissions -------------------------------------------------

export function fetchGradingSubmissions(params?: {
  status?: string;
  grading_company?: string;
  card_code?: string;
  limit?: number;
  offset?: number;
}): Promise<GradingSubmissionList> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.grading_company) query.set("grading_company", params.grading_company);
  if (params?.card_code) query.set("card_code", params.card_code);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return authedGet<GradingSubmissionList>(`/grading/submissions${qs ? `?${qs}` : ""}`);
}

export function fetchGradingSubmission(submissionId: number): Promise<GradingSubmission> {
  return authedGet<GradingSubmission>(`/grading/submissions/${submissionId}`);
}

export function createGradingSubmission(
  body: GradingSubmissionInput,
): Promise<GradingSubmission> {
  return authedPost<GradingSubmission>("/grading/submissions", body);
}

export function updateGradingSubmission(
  submissionId: number,
  body: Partial<GradingSubmissionInput>,
): Promise<GradingSubmission> {
  return authedPatch<GradingSubmission>(`/grading/submissions/${submissionId}`, body);
}

export function deleteGradingSubmission(submissionId: number): Promise<void> {
  return authedDelete(`/grading/submissions/${submissionId}`);
}

export function fetchGradingSummary(): Promise<GradingSummary> {
  return authedGet<GradingSummary>("/grading/summary");
}

// --- Wishlist / acquisition tracker --------------------------------------

export const WISHLIST_PRIORITIES = ["low", "medium", "high", "grail"] as const;
export type WishlistPriority = (typeof WISHLIST_PRIORITIES)[number];

export const WISHLIST_STATUSES = [
  "watching",
  "target_hit",
  "purchased",
  "passed",
  "removed",
] as const;
export type WishlistStatus = (typeof WISHLIST_STATUSES)[number];

export interface WishlistLatestPrices {
  yuyutei_sell: number | null;
  yuyutei_buy: number | null;
  snkrdunk_floor: number | null;
}

export interface WishlistItem {
  id: number;
  card_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  set_code: string;
  rarity: string;
  variant: string | null;
  language: string;
  priority: string;
  status: string;
  target_buy_price_jpy: number | null;
  max_buy_price_jpy: number | null;
  preferred_condition: string | null;
  preferred_source: string | null;
  desired_quantity: number;
  acquired_quantity: number;
  acquired_collection_item_id: number | null;
  notes: string | null;
  owned_quantity: number;
  latest_prices: WishlistLatestPrices;
  preferred_current_price_jpy: number | null;
  preferred_current_price_source: string | null;
  target_hit: boolean;
  gap_to_target_jpy: number | null;
  gap_to_target_pct: number | null;
  tags: CollectorTag[];
  created_at: string;
  updated_at: string;
}

export interface WishlistItemList {
  items: WishlistItem[];
  total: number;
  limit: number;
  offset: number;
  pagination: PaginationMeta;
}

export interface WishlistItemInput {
  card_id: number;
  priority?: WishlistPriority;
  target_buy_price_jpy?: number | null;
  max_buy_price_jpy?: number | null;
  preferred_condition?: string | null;
  preferred_source?: string | null;
  desired_quantity?: number;
  notes?: string | null;
}

export interface WishlistItemUpdateInput {
  priority?: WishlistPriority;
  status?: WishlistStatus;
  target_buy_price_jpy?: number | null;
  max_buy_price_jpy?: number | null;
  preferred_condition?: string | null;
  preferred_source?: string | null;
  desired_quantity?: number;
  notes?: string | null;
}

export interface WishlistMarkPurchasedInput {
  collection_item_id: number;
  acquired_quantity?: number;
}

export interface WishlistConvertToCollectionInput {
  quantity?: number;
  condition_label?: string | null;
  purchase_price_jpy?: number | null;
  purchase_date?: string | null;
  purchase_source?: string | null;
  target_sell_price_jpy?: number | null;
  status?: string;
  notes?: string | null;
}

export interface WishlistConvertToCollectionResponse {
  wishlist_item: WishlistItem;
  collection_item: CollectionItem;
}

export interface WishlistSummary {
  total_wishlist_items: number;
  watching: number;
  target_hit: number;
  purchased: number;
  passed: number;
  removed: number;
  grail_count: number;
  high_priority_count: number;
  total_target_budget_jpy: number;
  total_max_budget_jpy: number;
  items_owned_already: number;
  items_with_target_hit: number;
}

export function fetchWishlistItems(params?: {
  status?: string;
  priority?: string;
  card_code?: string;
  set_code?: string;
  rarity?: string;
  target_hit?: boolean;
  owned?: boolean;
  limit?: number;
  offset?: number;
}): Promise<WishlistItemList> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.priority) query.set("priority", params.priority);
  if (params?.card_code) query.set("card_code", params.card_code);
  if (params?.set_code) query.set("set_code", params.set_code);
  if (params?.rarity) query.set("rarity", params.rarity);
  if (params?.target_hit !== undefined) query.set("target_hit", String(params.target_hit));
  if (params?.owned !== undefined) query.set("owned", String(params.owned));
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return authedGet<WishlistItemList>(`/wishlist${qs ? `?${qs}` : ""}`);
}

export function fetchWishlistSummary(): Promise<WishlistSummary> {
  return authedGet<WishlistSummary>("/wishlist/summary");
}

// --- Wishlist analytics (see GET /analytics/wishlist) ----------------------

export interface WishlistAnalyticsSummary {
  total_items: number;
  watching_count: number;
  target_hit_count: number;
  purchased_count: number;
  passed_count: number;
  grail_count: number;
  high_priority_count: number;
  owned_already_count: number;
  total_target_budget_jpy: number;
  total_max_budget_jpy: number;
  total_current_price_jpy: number;
  budget_gap_to_target_jpy: number;
  budget_gap_to_max_jpy: number;
  average_target_price_jpy: number;
  median_target_price_jpy: number;
}

export interface WishlistAnalyticsBreakdownItem {
  key: string;
  label: string;
  item_count: number;
  desired_quantity: number;
  target_budget_jpy: number;
  max_budget_jpy: number;
  current_price_jpy: number;
  target_hit_count: number;
  owned_count: number;
  budget_weight_pct: number;
}

export interface WishlistAnalyticsBreakdowns {
  by_priority: WishlistAnalyticsBreakdownItem[];
  by_status: WishlistAnalyticsBreakdownItem[];
  by_set: WishlistAnalyticsBreakdownItem[];
  by_rarity: WishlistAnalyticsBreakdownItem[];
  by_preferred_source: WishlistAnalyticsBreakdownItem[];
  by_preferred_condition: WishlistAnalyticsBreakdownItem[];
}

export interface WishlistAnalyticsTargetItem {
  wishlist_item_id: number;
  card_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  set_code: string;
  rarity: string;
  priority: string;
  status: string;
  desired_quantity: number;
  owned_quantity: number;
  target_buy_price_jpy: number | null;
  max_buy_price_jpy: number | null;
  preferred_current_price_jpy: number | null;
  preferred_current_price_source: string | null;
  target_hit: boolean;
  gap_to_target_jpy: number | null;
  gap_to_target_pct: number | null;
}

export interface WishlistAnalyticsBudgetPlan {
  grail_targets: WishlistAnalyticsTargetItem[];
  high_priority_targets: WishlistAnalyticsTargetItem[];
  best_gap_to_target: WishlistAnalyticsTargetItem[];
  largest_budget_items: WishlistAnalyticsTargetItem[];
  already_owned: WishlistAnalyticsTargetItem[];
}

export interface WishlistAnalyticsPriceCoverage {
  items_with_current_price: number;
  items_missing_current_price: number;
  coverage_pct: number;
}

export interface WishlistAnalytics {
  summary: WishlistAnalyticsSummary;
  breakdowns: WishlistAnalyticsBreakdowns;
  target_hits: WishlistAnalyticsTargetItem[];
  budget_plan: WishlistAnalyticsBudgetPlan;
  price_coverage: WishlistAnalyticsPriceCoverage;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/analytics/wishlist/route.ts), same rationale as
 * fetchCollectionAnalytics - browser-side fetches to the backend's host
 * port are unreliable in Codespaces/forwarded-port environments, and this
 * endpoint needs the signed-in user's session forwarded server-side. */
export function fetchWishlistAnalytics(params?: {
  include_removed?: boolean;
  include_purchased?: boolean;
}): Promise<WishlistAnalytics> {
  const query = new URLSearchParams();
  if (params?.include_removed !== undefined) {
    query.set("include_removed", String(params.include_removed));
  }
  if (params?.include_purchased !== undefined) {
    query.set("include_purchased", String(params.include_purchased));
  }
  const qs = query.toString();
  return fetchAdminJson<WishlistAnalytics>(`/api/analytics/wishlist${qs ? `?${qs}` : ""}`);
}

// --- Sell decision support (see GET /analytics/sell-decisions) -------------

export type SellDecisionAction = "review_sell" | "hold" | "grade_first" | "missing_data" | "monitor";

export interface SellDecisionSummary {
  total_candidates: number;
  review_sell_count: number;
  hold_count: number;
  grade_first_count: number;
  missing_data_count: number;
  monitor_count: number;
  total_potential_sale_value_jpy: number;
  total_unrealized_pnl_jpy: number;
  average_score: number;
}

export interface SellDecisionLatestPrices {
  yuyutei_sell: number | null;
  yuyutei_buy: number | null;
  snkrdunk_floor: number | null;
}

export interface SellDecisionMarketContext {
  yuyutei_spread_pct: number | null;
  snkrdunk_vs_yuyutei_sell_gap_pct: number | null;
  related_opportunity_score: number | null;
  related_signal_types: string[];
}

export interface SellDecisionGrading {
  has_active_grading: boolean;
  latest_status: string | null;
  final_grade: string | null;
  graded_value_jpy: number | null;
}

export interface SellDecisionWishlistOverlap {
  is_on_wishlist: boolean;
  priority: string | null;
  status: string | null;
}

export interface SellDecisionCandidate {
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
  status: string;
  condition_label: string | null;
  score: number;
  recommended_action: SellDecisionAction;
  current_value_jpy: number | null;
  current_value_basis: string | null;
  cost_basis_jpy: number | null;
  unrealized_pnl_jpy: number | null;
  unrealized_pnl_pct: number | null;
  target_sell_price_jpy: number | null;
  above_target_sell: boolean;
  latest_prices: SellDecisionLatestPrices;
  market_context: SellDecisionMarketContext;
  grading: SellDecisionGrading;
  wishlist_overlap: SellDecisionWishlistOverlap;
  tags: string[];
  groups: string[];
  score_reasons: string[];
  warnings: string[];
}

export interface SellDecisionSupport {
  summary: SellDecisionSummary;
  candidates: SellDecisionCandidate[];
  limit: number;
  offset: number;
  pagination: PaginationMeta;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/analytics/sell-decisions/route.ts), same rationale as
 * fetchWishlistAnalytics/fetchCollectionAnalytics - browser-side fetches to
 * the backend's host port are unreliable in Codespaces/forwarded-port
 * environments, and this endpoint needs the signed-in user's session
 * forwarded server-side. */
export function fetchSellDecisions(params?: {
  valuation_mode?: "raw_market" | "graded_adjusted";
  include_sold?: boolean;
  min_score?: number;
  action?: SellDecisionAction;
  limit?: number;
  offset?: number;
}): Promise<SellDecisionSupport> {
  const query = new URLSearchParams();
  if (params?.valuation_mode) query.set("valuation_mode", params.valuation_mode);
  if (params?.include_sold !== undefined) query.set("include_sold", String(params.include_sold));
  if (params?.min_score !== undefined) query.set("min_score", String(params.min_score));
  if (params?.action) query.set("action", params.action);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return fetchAdminJson<SellDecisionSupport>(`/api/analytics/sell-decisions${qs ? `?${qs}` : ""}`);
}

// --- Buy decision support (see GET /analytics/buy-decisions) ---------------

export type BuyDecisionAction = "review_buy" | "wait" | "skip" | "missing_data" | "monitor";
export type BuySourcePreference = "auto" | "snkrdunk" | "yuyutei";
export type BuyDecisionPriorityFilter = "low" | "medium" | "high" | "grail";

export interface BuyDecisionSummary {
  total_candidates: number;
  review_buy_count: number;
  wait_count: number;
  skip_count: number;
  missing_data_count: number;
  monitor_count: number;
  target_hit_count: number;
  total_target_budget_jpy: number;
  total_current_cost_jpy: number;
  budget_gap_jpy: number;
  average_score: number;
}

export interface BuyDecisionLatestPrices {
  yuyutei_sell: number | null;
  yuyutei_buy: number | null;
  snkrdunk_floor: number | null;
}

export interface BuyDecisionMarketContext {
  snkrdunk_vs_yuyutei_sell_gap_pct: number | null;
  yuyutei_spread_pct: number | null;
  related_opportunity_score: number | null;
  related_signal_types: string[];
}

export interface BuyDecisionCandidate {
  wishlist_item_id: number;
  card_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  set_code: string;
  rarity: string;
  variant: string | null;
  language: string;
  score: number;
  recommended_action: BuyDecisionAction;
  priority: string;
  status: string;
  desired_quantity: number;
  owned_quantity: number;
  remaining_quantity: number;
  target_buy_price_jpy: number | null;
  max_buy_price_jpy: number | null;
  preferred_condition: string | null;
  preferred_source: string | null;
  current_price_jpy: number | null;
  current_price_source: string | null;
  target_hit: boolean;
  gap_to_target_jpy: number | null;
  gap_to_target_pct: number | null;
  gap_to_max_jpy: number | null;
  gap_to_max_pct: number | null;
  latest_prices: BuyDecisionLatestPrices;
  market_context: BuyDecisionMarketContext;
  tags: string[];
  groups: string[];
  score_reasons: string[];
  warnings: string[];
}

export interface BuyDecisionSupport {
  summary: BuyDecisionSummary;
  candidates: BuyDecisionCandidate[];
  limit: number;
  offset: number;
  pagination: PaginationMeta;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/analytics/buy-decisions/route.ts), same rationale as
 * fetchSellDecisions/fetchWishlistAnalytics - browser-side fetches to the
 * backend's host port are unreliable in Codespaces/forwarded-port
 * environments, and this endpoint needs the signed-in user's session
 * forwarded server-side. */
export function fetchBuyDecisions(params?: {
  source_preference?: BuySourcePreference;
  include_owned?: boolean;
  include_purchased?: boolean;
  min_score?: number;
  action?: BuyDecisionAction;
  priority?: BuyDecisionPriorityFilter;
  limit?: number;
  offset?: number;
}): Promise<BuyDecisionSupport> {
  const query = new URLSearchParams();
  if (params?.source_preference) query.set("source_preference", params.source_preference);
  if (params?.include_owned !== undefined) query.set("include_owned", String(params.include_owned));
  if (params?.include_purchased !== undefined) {
    query.set("include_purchased", String(params.include_purchased));
  }
  if (params?.min_score !== undefined) query.set("min_score", String(params.min_score));
  if (params?.action) query.set("action", params.action);
  if (params?.priority) query.set("priority", params.priority);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return fetchAdminJson<BuyDecisionSupport>(`/api/analytics/buy-decisions${qs ? `?${qs}` : ""}`);
}

// --- Grading ROI analytics (see GET /analytics/grading) --------------------

export interface GradingAnalyticsSummary {
  total_submissions: number;
  active_submissions: number;
  received_submissions: number;
  cancelled_submissions: number;
  total_declared_value_jpy: number;
  total_grading_cost_jpy: number;
  total_graded_value_jpy: number;
  total_raw_cost_basis_jpy: number;
  total_roi_jpy: number;
  total_roi_pct: number | null;
  average_grade: number | null;
  median_grade: number | null;
  profitable_count: number;
  unprofitable_count: number;
  missing_graded_value_count: number;
  missing_cost_basis_count: number;
  items_waiting_return: number;
}

export interface GradingAnalyticsBreakdownItem {
  key: string;
  label: string;
  submission_count: number;
  received_count: number;
  active_count: number;
  total_cost_jpy: number;
  graded_value_jpy: number;
  roi_jpy: number;
  roi_pct: number | null;
}

export interface GradingAnalyticsBreakdowns {
  by_status: GradingAnalyticsBreakdownItem[];
  by_company: GradingAnalyticsBreakdownItem[];
  by_grade: GradingAnalyticsBreakdownItem[];
  by_set: GradingAnalyticsBreakdownItem[];
  by_rarity: GradingAnalyticsBreakdownItem[];
}

export interface GradingAnalyticsFlags {
  profitable: boolean;
  missing_cost_basis: boolean;
  missing_graded_value: boolean;
  overdue: boolean;
  active: boolean;
}

export interface GradingAnalyticsSubmission {
  grading_submission_id: number;
  collection_item_id: number;
  card_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  set_code: string;
  rarity: string;
  variant: string | null;
  quantity: number;
  grading_company: string;
  submission_name: string | null;
  submission_status: string;
  declared_value_jpy: number | null;
  grading_fee_jpy: number | null;
  shipping_fee_jpy: number | null;
  insurance_fee_jpy: number | null;
  other_fee_jpy: number | null;
  total_cost_jpy: number;
  purchase_price_jpy: number | null;
  raw_cost_basis_jpy: number | null;
  graded_value_jpy: number | null;
  roi_jpy: number | null;
  roi_pct: number | null;
  submitted_at: string | null;
  expected_return_date: string | null;
  received_at: string | null;
  days_in_grading: number | null;
  final_grade: string | null;
  cert_number: string | null;
  tracking_number: string | null;
  notes: string | null;
  tags: string[];
  groups: string[];
  flags: GradingAnalyticsFlags;
}

export interface GradingAnalyticsRoi {
  best_roi_submissions: GradingAnalyticsSubmission[];
  worst_roi_submissions: GradingAnalyticsSubmission[];
  highest_graded_value: GradingAnalyticsSubmission[];
  highest_grading_cost: GradingAnalyticsSubmission[];
  missing_value_or_cost: GradingAnalyticsSubmission[];
}

export interface GradingAnalyticsPending {
  waiting_return: GradingAnalyticsSubmission[];
  overdue: GradingAnalyticsSubmission[];
  expected_next_30d: GradingAnalyticsSubmission[];
}

export interface GradingAnalytics {
  summary: GradingAnalyticsSummary;
  breakdowns: GradingAnalyticsBreakdowns;
  roi: GradingAnalyticsRoi;
  pending: GradingAnalyticsPending;
  submissions: GradingAnalyticsSubmission[];
  limit: number;
  offset: number;
  pagination: PaginationMeta;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/analytics/grading/route.ts), same rationale as
 * fetchBuyDecisions/fetchSellDecisions - browser-side fetches to the
 * backend's host port are unreliable in Codespaces/forwarded-port
 * environments, and this endpoint needs the signed-in user's session
 * forwarded server-side. */
export function fetchGradingAnalytics(params?: {
  include_cancelled?: boolean;
  grading_company?: string;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<GradingAnalytics> {
  const query = new URLSearchParams();
  if (params?.include_cancelled !== undefined) {
    query.set("include_cancelled", String(params.include_cancelled));
  }
  if (params?.grading_company) query.set("grading_company", params.grading_company);
  if (params?.status) query.set("status", params.status);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return fetchAdminJson<GradingAnalytics>(`/api/analytics/grading${qs ? `?${qs}` : ""}`);
}

// --- Portfolio risk analytics (see GET /analytics/portfolio-risk) ----------

export type PortfolioRiskLevel = "low" | "medium" | "high" | "critical";

export interface PortfolioRiskSummary {
  risk_score: number;
  risk_level: PortfolioRiskLevel;
  total_value_jpy: number;
  total_cost_basis_jpy: number;
  largest_single_card_weight_pct: number;
  top_5_weight_pct: number;
  top_10_weight_pct: number;
  largest_set_weight_pct: number;
  largest_rarity_weight_pct: number;
  missing_price_count: number;
  missing_cost_basis_count: number;
  stale_price_count: number;
  wide_spread_count: number;
  active_grading_count: number;
  wishlist_overlap_count: number;
}

export interface PortfolioRiskCard {
  card_id: number;
  collection_item_id: number;
  card_code: string;
  name_en: string | null;
  set_code: string;
  rarity: string;
  quantity: number;
  value_jpy: number | null;
  portfolio_weight_pct: number | null;
  cost_basis_jpy: number | null;
  warnings: string[];
}

export interface PortfolioRiskDataQualityCard extends PortfolioRiskCard {
  issue: string;
  latest_observed_at: string | null;
  suggested_action: string;
}

export interface PortfolioRiskLiquidityCard extends PortfolioRiskCard {
  yuyutei_sell_jpy: number | null;
  yuyutei_buy_jpy: number | null;
  spread_pct: number | null;
  snkrdunk_floor_jpy: number | null;
  listing_count: number | null;
}

export interface PortfolioRiskGradingCard extends PortfolioRiskCard {
  grading_company: string | null;
  submission_status: string | null;
  grading_cost_jpy: number | null;
  expected_return_date: string | null;
  overdue: boolean;
}

export interface PortfolioRiskWishlistCard {
  wishlist_item_id: number;
  card_id: number;
  card_code: string;
  name_en: string | null;
  set_code: string;
  rarity: string;
  wishlist_priority: string;
  wishlist_status: string;
  owned_quantity: number;
  desired_quantity: number;
  suggested_action: string;
}

export interface PortfolioRiskExposureItem {
  key: string;
  label: string;
  quantity: number;
  value_jpy: number;
  cost_basis_jpy: number;
  portfolio_weight_pct: number;
  pnl_jpy: number;
  pnl_pct: number | null;
  risk_flags: string[];
}

export interface PortfolioRiskConcentration {
  score: number;
  level: PortfolioRiskLevel;
  warnings: string[];
  top_cards: PortfolioRiskCard[];
  top_sets: PortfolioRiskExposureItem[];
  top_rarities: PortfolioRiskExposureItem[];
}

export interface PortfolioRiskDataQuality {
  score: number;
  level: PortfolioRiskLevel;
  warnings: string[];
  missing_prices: PortfolioRiskDataQualityCard[];
  missing_cost_basis: PortfolioRiskDataQualityCard[];
  stale_prices: PortfolioRiskDataQualityCard[];
}

export interface PortfolioRiskLiquidityProxy {
  score: number;
  level: PortfolioRiskLevel;
  warnings: string[];
  wide_spread_cards: PortfolioRiskLiquidityCard[];
  low_listing_cards: PortfolioRiskLiquidityCard[];
}

export interface PortfolioRiskGradingExposure {
  score: number;
  level: PortfolioRiskLevel;
  warnings: string[];
  active_grading_items: PortfolioRiskGradingCard[];
  high_cost_pending_items: PortfolioRiskGradingCard[];
}

export interface PortfolioRiskWishlistOverlap {
  score: number;
  level: PortfolioRiskLevel;
  warnings: string[];
  owned_wishlist_items: PortfolioRiskWishlistCard[];
}

export interface PortfolioRiskBreakdown {
  concentration: PortfolioRiskConcentration;
  data_quality: PortfolioRiskDataQuality;
  liquidity_proxy: PortfolioRiskLiquidityProxy;
  grading_exposure: PortfolioRiskGradingExposure;
  wishlist_overlap: PortfolioRiskWishlistOverlap;
}

export interface PortfolioRiskExposures {
  by_set: PortfolioRiskExposureItem[];
  by_rarity: PortfolioRiskExposureItem[];
  by_variant: PortfolioRiskExposureItem[];
  by_language: PortfolioRiskExposureItem[];
  by_tag: PortfolioRiskExposureItem[];
  by_group: PortfolioRiskExposureItem[];
}

export type PortfolioRiskFlagSeverity = "info" | "warning" | "critical";
export type PortfolioRiskSuggestedAction =
  | "review_concentration"
  | "fix_missing_prices"
  | "fix_cost_basis"
  | "review_stale_prices"
  | "review_wide_spreads"
  | "review_grading_exposure"
  | "update_wishlist_status"
  | "none";

export interface PortfolioRiskFlag {
  flag_type: string;
  severity: PortfolioRiskFlagSeverity;
  message: string;
  related_cards: string[];
  suggested_action: PortfolioRiskSuggestedAction;
}

export interface PortfolioRisk {
  summary: PortfolioRiskSummary;
  risk_breakdown: PortfolioRiskBreakdown;
  exposures: PortfolioRiskExposures;
  recommendation_flags: PortfolioRiskFlag[];
}

/** Routed through the Next.js server proxy (see
 * src/app/api/analytics/portfolio-risk/route.ts), same rationale as
 * fetchGradingAnalytics/fetchSellDecisions - browser-side fetches to the
 * backend's host port are unreliable in Codespaces/forwarded-port
 * environments, and this endpoint needs the signed-in user's session
 * forwarded server-side. */
export function fetchPortfolioRisk(params?: {
  valuation_mode?: "raw_market" | "graded_adjusted";
  include_sold?: boolean;
}): Promise<PortfolioRisk> {
  const query = new URLSearchParams();
  if (params?.valuation_mode) query.set("valuation_mode", params.valuation_mode);
  if (params?.include_sold !== undefined) query.set("include_sold", String(params.include_sold));
  const qs = query.toString();
  return fetchAdminJson<PortfolioRisk>(`/api/analytics/portfolio-risk${qs ? `?${qs}` : ""}`);
}

// --- Analytics digest (see GET /analytics/digest) ---------------------------

export interface AnalyticsDigestSummary {
  valuation_mode: ValuationMode;
  generated_at: string;
  collection_value_jpy: number;
  graded_adjusted_value_jpy: number;
  portfolio_risk_score: number;
  portfolio_risk_level: PortfolioRiskLevel;
  wishlist_target_hits: number;
  buy_review_count: number;
  sell_review_count: number;
  grading_roi_jpy: number;
  grading_active_count: number;
  missing_cost_basis_count: number;
  missing_price_count: number;
}

export interface AnalyticsDigestCollectionSection {
  total_items: number;
  total_quantity: number;
  total_cost_basis_jpy: number;
  raw_market_value_jpy: number;
  graded_adjusted_value_jpy: number;
  largest_set_exposure: CollectionAnalyticsBreakdownItem | null;
  largest_rarity_exposure: CollectionAnalyticsBreakdownItem | null;
}

export interface AnalyticsDigestWishlistSection {
  total_items: number;
  grail_count: number;
  high_priority_count: number;
  target_hit_count: number;
  total_target_budget_jpy: number;
  price_coverage_pct: number;
}

export interface AnalyticsDigestBuyDecisionsSection {
  review_buy_count: number;
  wait_count: number;
  missing_data_count: number;
  top_review_buy: BuyDecisionCandidate[];
}

export interface AnalyticsDigestSellDecisionsSection {
  review_sell_count: number;
  grade_first_count: number;
  missing_data_count: number;
  top_review_sell: SellDecisionCandidate[];
}

export interface AnalyticsDigestGradingSection {
  active_submissions: number;
  received_submissions: number;
  total_grading_cost_jpy: number;
  total_graded_value_jpy: number;
  total_roi_jpy: number;
  overdue_count: number;
  best_roi: GradingAnalyticsSubmission[];
  worst_roi: GradingAnalyticsSubmission[];
}

export interface AnalyticsDigestPortfolioRiskSection {
  risk_score: number;
  risk_level: PortfolioRiskLevel;
  concentration_score: number;
  data_quality_score: number;
  liquidity_proxy_score: number;
  grading_exposure_score: number;
  wishlist_overlap_score: number;
  top_recommendation_flags: PortfolioRiskFlag[];
}

export interface AnalyticsDigestSections {
  collection: AnalyticsDigestCollectionSection;
  wishlist: AnalyticsDigestWishlistSection;
  buy_decisions: AnalyticsDigestBuyDecisionsSection;
  sell_decisions: AnalyticsDigestSellDecisionsSection;
  grading: AnalyticsDigestGradingSection;
  portfolio_risk: AnalyticsDigestPortfolioRiskSection;
}

export interface AnalyticsDigestPriorityItem {
  card_id: number | null;
  card_code: string | null;
  name_en: string | null;
  score: number | null;
  risk_level: string | null;
  severity: string | null;
  message: string;
  link: string;
}

export interface AnalyticsDigestPriorityItems {
  top_buy_decisions: AnalyticsDigestPriorityItem[];
  top_sell_decisions: AnalyticsDigestPriorityItem[];
  top_risk_flags: AnalyticsDigestPriorityItem[];
  wishlist_target_hits: AnalyticsDigestPriorityItem[];
  grading_overdue: AnalyticsDigestPriorityItem[];
  missing_data: AnalyticsDigestPriorityItem[];
}

export interface AnalyticsDigest {
  summary: AnalyticsDigestSummary;
  sections: AnalyticsDigestSections;
  priority_items: AnalyticsDigestPriorityItems;
  deterministic_summary_lines: string[];
}

export interface AnalyticsDigestReport {
  id: number;
  created_at: string;
  valuation_mode: ValuationMode;
  summary: AnalyticsDigestSummary;
  sections: AnalyticsDigestSections;
  priority_items: AnalyticsDigestPriorityItems;
  deterministic_summary_lines: string[];
  payload: Record<string, unknown>;
}

export interface AnalyticsDigestReportSummary {
  id: number;
  created_at: string;
  valuation_mode: ValuationMode;
  collection_value_jpy: number | null;
  graded_adjusted_value_jpy: number | null;
  portfolio_risk_score: number | null;
  portfolio_risk_level: string | null;
  wishlist_target_hits: number;
  buy_review_count: number;
  sell_review_count: number;
  grading_roi_jpy: number | null;
}

export interface AnalyticsDigestReportListResponse {
  reports: AnalyticsDigestReportSummary[];
  total: number;
  limit: number;
  offset: number;
  pagination: PaginationMeta;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/analytics/digest/route.ts) - same rationale as
 * fetchPortfolioRisk/fetchGradingAnalytics. */
export function fetchAnalyticsDigest(params?: {
  valuation_mode?: ValuationMode;
}): Promise<AnalyticsDigest> {
  const query = new URLSearchParams();
  if (params?.valuation_mode) query.set("valuation_mode", params.valuation_mode);
  const qs = query.toString();
  return fetchAdminJson<AnalyticsDigest>(`/api/analytics/digest${qs ? `?${qs}` : ""}`);
}

/** Routed through the Next.js server proxy (see
 * src/app/api/analytics/digest/latest/route.ts). Throws AdminNotFoundError
 * when no digest has been generated yet. */
export function fetchLatestAnalyticsDigest(params?: {
  valuation_mode?: ValuationMode;
}): Promise<AnalyticsDigestReport> {
  const query = new URLSearchParams();
  if (params?.valuation_mode) query.set("valuation_mode", params.valuation_mode);
  const qs = query.toString();
  return fetchAdminJson<AnalyticsDigestReport>(`/api/analytics/digest/latest${qs ? `?${qs}` : ""}`);
}

/** Routed through the Next.js server proxy (see
 * src/app/api/analytics/digest/reports/route.ts). */
export function fetchAnalyticsDigestReports(params?: {
  valuation_mode?: ValuationMode;
  limit?: number;
  offset?: number;
}): Promise<AnalyticsDigestReportListResponse> {
  const query = new URLSearchParams();
  if (params?.valuation_mode) query.set("valuation_mode", params.valuation_mode);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return fetchAdminJson<AnalyticsDigestReportListResponse>(
    `/api/analytics/digest/reports${qs ? `?${qs}` : ""}`,
  );
}

/** Routed through the Next.js server proxy (see
 * src/app/api/analytics/digest/reports/[id]/route.ts). */
export function fetchAnalyticsDigestReport(reportId: number): Promise<AnalyticsDigestReport> {
  return fetchAdminJson<AnalyticsDigestReport>(`/api/analytics/digest/reports/${reportId}`);
}

export interface GenerateAnalyticsDigestRequest {
  valuation_mode?: ValuationMode;
}

export interface GenerateAnalyticsDigestResponse {
  report_id: number;
  valuation_mode: ValuationMode;
  portfolio_risk_score: number;
  buy_review_count: number;
  sell_review_count: number;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/actions/generate-analytics-digest/route.ts). */
export function triggerGenerateAnalyticsDigest(
  body: GenerateAnalyticsDigestRequest,
): Promise<GenerateAnalyticsDigestResponse> {
  return fetchAdminJson<GenerateAnalyticsDigestResponse>(
    "/api/admin/actions/generate-analytics-digest",
    { method: "POST", body },
  );
}

export function fetchWishlistItem(wishlistItemId: number): Promise<WishlistItem> {
  return authedGet<WishlistItem>(`/wishlist/${wishlistItemId}`);
}

export function createWishlistItem(body: WishlistItemInput): Promise<WishlistItem> {
  return authedPost<WishlistItem>("/wishlist", body);
}

export function updateWishlistItem(
  wishlistItemId: number,
  body: WishlistItemUpdateInput,
): Promise<WishlistItem> {
  return authedPatch<WishlistItem>(`/wishlist/${wishlistItemId}`, body);
}

/** Soft delete - the backend sets status=removed rather than physically
 * deleting the row, and returns the updated item (not 204). */
export function removeWishlistItem(wishlistItemId: number): Promise<WishlistItem> {
  const path = `/wishlist/${wishlistItemId}`;
  return (async () => {
    const headers = await authedHeaders();
    const res = await fetch(`${API_URL}${path}`, { method: "DELETE", headers });
    if (res.status === 401) throw new AuthRequiredError();
    if (!res.ok) throw await _errorFromResponse(res, path);
    return res.json() as Promise<WishlistItem>;
  })();
}

export function markWishlistItemPurchased(
  wishlistItemId: number,
  body: WishlistMarkPurchasedInput,
): Promise<WishlistItem> {
  return authedPost<WishlistItem>(`/wishlist/${wishlistItemId}/mark-purchased`, body);
}

export function convertWishlistItemToCollection(
  wishlistItemId: number,
  body: WishlistConvertToCollectionInput,
): Promise<WishlistConvertToCollectionResponse> {
  return authedPost<WishlistConvertToCollectionResponse>(
    `/wishlist/${wishlistItemId}/convert-to-collection`,
    body,
  );
}

export interface WishlistImportRowError {
  row_number: number;
  card_code: string | null;
  error: string;
}

export interface WishlistImportPreviewRow {
  row_number: number;
  card_code: string;
  matched_card_id: number;
  action: string;
  priority: string;
  status: string;
}

export interface WishlistImportSummary {
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  created: number;
  updated: number;
  skipped: number;
}

export interface WishlistImportResponse {
  dry_run: boolean;
  mode: string;
  summary: WishlistImportSummary;
  errors: WishlistImportRowError[];
  preview: WishlistImportPreviewRow[];
}

/** Downloads /wishlist/export.csv through the Next.js proxy (see
 * src/app/api/wishlist/export/route.ts) and triggers a browser file
 * download, using the filename the backend set via Content-Disposition. */
export async function downloadWishlistCsv(): Promise<void> {
  const res = await fetch("/api/wishlist/export", {
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
    "wishlist_export.csv";

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/** Uploads a wishlist CSV through the Next.js proxy (see
 * src/app/api/wishlist/import/route.ts). dry_run defaults to true on the
 * backend if omitted, but callers here always pass it explicitly. */
export async function importWishlistCsv(
  file: File,
  params: { dryRun: boolean; mode: CollectionImportMode },
): Promise<WishlistImportResponse> {
  const query = new URLSearchParams({
    dry_run: String(params.dryRun),
    mode: params.mode,
  });

  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`/api/wishlist/import?${query.toString()}`, {
    method: "POST",
    body: formData,
  });

  const details = await res
    .json()
    .catch(
      () =>
        null as
          | (Partial<WishlistImportResponse> & { error?: string; detail?: string })
          | null,
    );

  if (!res.ok || !details) {
    throw new Error(
      details?.error || details?.detail || `Import failed with status ${res.status}`,
    );
  }

  return details as WishlistImportResponse;
}

/** Same as importWishlistCsv above, but background=true - the backend
 * returns 202 immediately with a file_job_id instead of the full import
 * result; poll fetchFileJob(file_job_id) for progress/status/errors. */
export async function importWishlistCsvBackground(
  file: File,
  params: { dryRun: boolean; mode: CollectionImportMode },
): Promise<FileJobCreated> {
  const query = new URLSearchParams({
    dry_run: String(params.dryRun),
    mode: params.mode,
    background: "true",
  });

  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`/api/wishlist/import?${query.toString()}`, {
    method: "POST",
    body: formData,
  });

  const details = await res
    .json()
    .catch(() => null as (Partial<FileJobCreated> & { error?: string; detail?: string }) | null);

  if (!res.ok || !details) {
    throw new Error(
      details?.error || details?.detail || `Import failed with status ${res.status}`,
    );
  }

  return details as FileJobCreated;
}

/** Creates a background wishlist export job - poll fetchFileJob(id) and
 * downloadFileJob(id) once status=success. Routed through the Next.js
 * server proxy (see src/app/api/wishlist/export/job/route.ts). */
export async function createWishlistExportJob(): Promise<FileJobCreated> {
  return fetchAdminJson<FileJobCreated>("/api/wishlist/export/job", {
    method: "POST",
    body: {},
  });
}

// --- Dashboard personalization --------------------------------------------

export const DASHBOARD_WIDGET_IDS = [
  "portfolio_summary",
  "portfolio_chart",
  "wishlist_targets",
  "top_opportunities",
  "grading_status",
  "market_report",
  "collection_quality",
  "recent_signal_events",
  "data_freshness",
  "backup_status",
  "workflow_status",
] as const;
export type DashboardWidgetId = (typeof DASHBOARD_WIDGET_IDS)[number];

export const DASHBOARD_TIMEFRAMES = ["7d", "30d", "90d", "all"] as const;
export type DashboardTimeframe = (typeof DASHBOARD_TIMEFRAMES)[number];

export interface DashboardPreferences {
  layout: string[];
  hidden_widgets: string[];
  pinned_cards: number[];
  default_timeframe: string;
  show_raw_market_value: boolean;
  show_graded_adjusted_value: boolean;
  show_wishlist_budget: boolean;
  show_grading_costs: boolean;
}

export interface DashboardPreferencesInput {
  layout?: string[];
  hidden_widgets?: string[];
  pinned_cards?: number[];
  default_timeframe?: DashboardTimeframe;
  show_raw_market_value?: boolean;
  show_graded_adjusted_value?: boolean;
  show_wishlist_budget?: boolean;
  show_grading_costs?: boolean;
}

/** Mirrors services/api/app/services/dashboard.py's DEFAULT_PREFERENCES -
 * used by the frontend's "Reset to defaults" action, which just PATCHes this
 * back rather than needing a dedicated reset endpoint. */
export const DEFAULT_DASHBOARD_PREFERENCES: DashboardPreferences = {
  layout: [
    "portfolio_summary",
    "wishlist_targets",
    "top_opportunities",
    "grading_status",
    "market_report",
    "collection_quality",
    "recent_signal_events",
    "data_freshness",
  ],
  hidden_widgets: [],
  pinned_cards: [],
  default_timeframe: "30d",
  show_raw_market_value: true,
  show_graded_adjusted_value: true,
  show_wishlist_budget: true,
  show_grading_costs: true,
};

export interface PortfolioSummaryWidget {
  total_cost_basis_jpy: number | null;
  market_floor_value_jpy: number | null;
  graded_adjusted_value_jpy: number | null;
  pnl_vs_market_floor_jpy: number | null;
  pnl_vs_market_floor_pct: number | null;
  pnl_vs_graded_adjusted_jpy: number | null;
  pnl_vs_graded_adjusted_pct: number | null;
}

export interface PortfolioChartPoint {
  created_at: string;
  market_floor_value_jpy: number | null;
  graded_adjusted_value_jpy: number | null;
}

export interface PortfolioChartWidget {
  timeframe: string;
  points: PortfolioChartPoint[];
}

export interface WishlistTargetsWidget {
  items: WishlistItem[];
  total_target_hit: number;
  total_target_budget_jpy: number;
  total_max_budget_jpy: number;
}

export interface TopOpportunitiesWidget {
  opportunities: MarketOpportunity[];
}

export interface GradingStatusWidget {
  total_submissions: number;
  submitted_or_grading_count: number;
  received_count: number;
  total_grading_cost_jpy: number;
}

export interface MarketReportWidget {
  report_id: number | null;
  report_date: string | null;
  total_opportunities: number | null;
  highest_score: number | null;
  deterministic_summary_lines: string[];
}

export interface CollectionQualityWidget {
  missing_purchase_price_count: number;
  missing_condition_count: number;
  missing_target_sell_count: number;
}

export interface RecentSignalEventsWidget {
  events: MarketSignalEvent[];
}

export interface DataFreshnessWidget {
  latest_refresh_at: string | null;
  latest_refresh_status: string | null;
  missing_recent_price_count: number;
  stale_mapping_price_count: number;
}

export interface BackupStatusWidget {
  tracked: boolean;
  last_backup_at: string | null;
  message: string | null;
}

export interface WorkflowStatusWidget {
  run_id: number | null;
  status: string | null;
  market_report_id: number | null;
  telegram_digest_status: string | null;
  finished_at: string | null;
  error_count_24h: number;
  warning_count_24h: number;
}

export interface DashboardWidgets {
  portfolio_summary: PortfolioSummaryWidget;
  portfolio_chart: PortfolioChartWidget;
  wishlist_targets: WishlistTargetsWidget;
  top_opportunities: TopOpportunitiesWidget;
  grading_status: GradingStatusWidget;
  market_report: MarketReportWidget;
  collection_quality: CollectionQualityWidget;
  recent_signal_events: RecentSignalEventsWidget;
  data_freshness: DataFreshnessWidget;
  backup_status: BackupStatusWidget;
  workflow_status: WorkflowStatusWidget;
}

export interface DashboardOverview {
  preferences: DashboardPreferences;
  widgets: DashboardWidgets;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/dashboard/preferences/route.ts), which forwards the caller's
 * session as a bearer token - same reasoning as the collection/wishlist CSV
 * proxy routes. */
export function fetchDashboardPreferences(): Promise<DashboardPreferences> {
  return fetchAdminJson<DashboardPreferences>("/api/dashboard/preferences");
}

export function updateDashboardPreferences(
  body: DashboardPreferencesInput,
): Promise<DashboardPreferences> {
  return fetchAdminJson<DashboardPreferences>("/api/dashboard/preferences", {
    method: "PATCH",
    body,
  });
}

/** Routed through the Next.js server proxy (see
 * src/app/api/dashboard/overview/route.ts). */
export function fetchDashboardOverview(): Promise<DashboardOverview> {
  return fetchAdminJson<DashboardOverview>("/api/dashboard/overview");
}

// --- Collector notes / activity -----------------------------------------

export const ACTIVITY_EVENT_SOURCES = [
  "collection",
  "wishlist",
  "grading",
  "market_signal",
  "market_report",
  "backup",
  "workflow",
  "note",
] as const;

export interface CollectorNote {
  id: number;
  note_type: string;
  card_id: number | null;
  collection_item_id: number | null;
  wishlist_item_id: number | null;
  grading_submission_id: number | null;
  market_signal_event_id: number | null;
  market_report_id: number | null;
  title: string | null;
  body: string;
  pinned: boolean;
  created_at: string;
  updated_at: string;
}

export interface CollectorActivityEvent {
  id: number;
  event_type: string;
  event_source: string;
  card_id: number | null;
  card_code: string | null;
  name_en: string | null;
  name_jp: string | null;
  collection_item_id: number | null;
  wishlist_item_id: number | null;
  grading_submission_id: number | null;
  market_signal_event_id: number | null;
  market_report_id: number | null;
  market_workflow_run_id: number | null;
  title: string;
  message: string | null;
  created_at: string;
  payload: Record<string, unknown> | null;
}

export interface CollectorActivityListSummary {
  total_events: number;
  by_source: Record<string, number>;
  by_type: Record<string, number>;
}

export interface CollectorActivityListResponse {
  summary: CollectorActivityListSummary;
  events: CollectorActivityEvent[];
  limit: number;
  offset: number;
  pagination: PaginationMeta;
}

export interface CollectorActivitySummary {
  today_count: number;
  last_7d_count: number;
  last_30d_count: number;
  by_source: Record<string, number>;
  recent_events: CollectorActivityEvent[];
}

export function fetchCollectorActivity(params?: {
  event_source?: string;
  event_type?: string;
  card_id?: number;
  limit?: number;
  offset?: number;
}): Promise<CollectorActivityListResponse> {
  const query = new URLSearchParams();
  if (params?.event_source) query.set("event_source", params.event_source);
  if (params?.event_type) query.set("event_type", params.event_type);
  if (params?.card_id !== undefined) query.set("card_id", String(params.card_id));
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return authedGet<CollectorActivityListResponse>(`/collector/activity${qs ? `?${qs}` : ""}`);
}

export function fetchCollectorActivitySummary(): Promise<CollectorActivitySummary> {
  return authedGet<CollectorActivitySummary>("/collector/activity/summary");
}

export interface CollectorNoteList {
  items: CollectorNote[];
  total: number;
  limit: number;
  offset: number;
  pagination: PaginationMeta;
}

export function fetchCollectorNotes(params?: {
  note_type?: string;
  limit?: number;
  offset?: number;
}): Promise<CollectorNoteList> {
  const query = new URLSearchParams();
  if (params?.note_type) query.set("note_type", params.note_type);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return authedGet<CollectorNoteList>(`/collector/notes${qs ? `?${qs}` : ""}`);
}

export function createCollectorNote(body: {
  note_type: string;
  body: string;
  card_id?: number;
  collection_item_id?: number;
  title?: string;
  pinned?: boolean;
}): Promise<CollectorNote> {
  return authedPost<CollectorNote>("/collector/notes", body);
}

// --- Search --------------------------------------------------------------

export const SEARCH_TYPES = [
  "cards",
  "collection",
  "wishlist",
  "grading",
  "notes",
  "activity",
  "signals",
  "opportunities",
  "reports",
] as const;
export type SearchType = (typeof SEARCH_TYPES)[number];

export interface SearchResult {
  type: SearchType;
  id: number;
  score: number;
  title: string;
  subtitle: string;
  matched_fields: string[];
  card_id: number | null;
  card_code: string | null;
  name_en: string | null;
  name_jp: string | null;
  url: string;
  metadata: Record<string, unknown>;
}

export interface SearchSummary {
  total_results: number;
  by_type: Record<SearchType, number>;
}

export interface SearchResponse {
  query: string;
  summary: SearchSummary;
  results: SearchResult[];
  limit: number;
  offset: number;
  pagination: PaginationMeta;
}

export interface SearchSuggestion {
  label: string;
  type: string;
  url: string;
}

export interface SearchSuggestionsResponse {
  suggestions: SearchSuggestion[];
}

/** Routed through the Next.js server proxy (see
 * src/app/api/search/route.ts), which forwards the caller's session as a
 * bearer token - same reasoning as the dashboard overview/preferences proxy
 * routes. */
export function fetchSearch(params: {
  q: string;
  types?: SearchType[];
  limit?: number;
  offset?: number;
}): Promise<SearchResponse> {
  const query = new URLSearchParams({ q: params.q });
  if (params.types && params.types.length > 0) query.set("types", params.types.join(","));
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  return fetchAdminJson<SearchResponse>(`/api/search?${query.toString()}`);
}

/** Routed through the Next.js server proxy (see
 * src/app/api/search/suggestions/route.ts). */
export function fetchSearchSuggestions(params?: {
  q?: string;
  limit?: number;
}): Promise<SearchSuggestionsResponse> {
  const query = new URLSearchParams();
  if (params?.q) query.set("q", params.q);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  const qs = query.toString();
  return fetchAdminJson<SearchSuggestionsResponse>(
    `/api/search/suggestions${qs ? `?${qs}` : ""}`,
  );
}

// --- App logs / observability -------------------------------------------

export const APP_LOG_LEVELS = ["debug", "info", "warning", "error", "critical"] as const;
export type AppLogLevel = (typeof APP_LOG_LEVELS)[number];

export interface AppLogEvent {
  id: number;
  created_at: string;
  level: AppLogLevel;
  service: string;
  event_type: string;
  message: string;
  context: Record<string, unknown> | null;
  traceback: string | null;
  related_run_id: number | null;
  related_entity_type: string | null;
  related_entity_id: number | null;
}

export interface AppLogSummary {
  total_logs: number;
  error_count: number;
  warning_count: number;
  critical_count: number;
  by_service: Record<string, number>;
  by_event_type: Record<string, number>;
}

export interface AppLogListResponse {
  summary: AppLogSummary;
  logs: AppLogEvent[];
  limit: number;
  offset: number;
  pagination: PaginationMeta;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/logs/route.ts). */
export function fetchAppLogs(params?: {
  level?: string;
  service?: string;
  event_type?: string;
  q?: string;
  since_hours?: number;
  limit?: number;
  offset?: number;
}): Promise<AppLogListResponse> {
  const query = new URLSearchParams();
  if (params?.level) query.set("level", params.level);
  if (params?.service) query.set("service", params.service);
  if (params?.event_type) query.set("event_type", params.event_type);
  if (params?.q) query.set("q", params.q);
  if (params?.since_hours !== undefined) query.set("since_hours", String(params.since_hours));
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return fetchAdminJson<AppLogListResponse>(`/api/admin/logs${qs ? `?${qs}` : ""}`);
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/logs/[id]/route.ts). */
export function fetchAppLog(logId: number): Promise<AppLogEvent> {
  return fetchAdminJson<AppLogEvent>(`/api/admin/logs/${logId}`);
}

export interface AppLogPruneRequest {
  older_than_days: number;
  dry_run: boolean;
  confirm?: string | null;
}

export interface AppLogPruneResponse {
  dry_run: boolean;
  older_than_days: number;
  would_delete: number;
  deleted: number;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/logs/prune/route.ts). */
export function pruneAppLogs(body: AppLogPruneRequest): Promise<AppLogPruneResponse> {
  return fetchAdminJson<AppLogPruneResponse>("/api/admin/logs/prune", {
    method: "POST",
    body,
  });
}

export interface ObservabilitySummary {
  status: string;
  last_24h: {
    critical: number;
    error: number;
    warning: number;
    info: number;
  };
  latest_error: AppLogEvent | null;
  latest_market_workflow_run: Record<string, unknown> | null;
  latest_price_refresh_run: Record<string, unknown> | null;
  latest_backup: Record<string, unknown> | null;
  latest_system_check_status: string | null;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/observability/summary/route.ts). */
export function fetchObservabilitySummary(): Promise<ObservabilitySummary> {
  return fetchAdminJson<ObservabilitySummary>("/api/admin/observability/summary");
}

export interface ReleaseReadiness {
  system_check_status: "ok" | "warning" | "critical";
  critical_logs_last_24h: number;
  latest_backup_available: boolean;
}

export interface ReleaseStatus {
  version: string;
  git_commit: string;
  build_time: string;
  app_env: string;
  latest_market_workflow_run: Record<string, unknown> | null;
  latest_system_check: SystemCheckResponse;
  latest_backup: Record<string, unknown> | null;
  latest_error: AppLogEvent | null;
  release_readiness: ReleaseReadiness;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/release-status/route.ts) - same reasoning as
 * fetchObservabilitySummary. */
export function fetchReleaseStatus(): Promise<ReleaseStatus> {
  return fetchAdminJson<ReleaseStatus>("/api/admin/release-status");
}

export interface WebVersionInfo {
  version: string;
  git_commit: string;
  build_time: string;
}

export interface ApiVersionInfo {
  version: string;
  git_commit: string;
}

export interface VersionInfo {
  web: WebVersionInfo;
  api: ApiVersionInfo | null;
}

/** Fetches src/app/api/version/route.ts directly (not through
 * fetchAdminJson - this route needs no admin token, it's the same
 * unauthenticated shape as the backend's own GET /version). */
export async function fetchVersionInfo(): Promise<VersionInfo> {
  const res = await fetch("/api/version", { cache: "no-store" });
  if (!res.ok) throw new Error(`Request to /api/version failed with status ${res.status}`);
  return res.json() as Promise<VersionInfo>;
}

// --- saved views ------------------------------------------------------------
//
// Single-user saved filter/sort/column presets (see docs/operations.md,
// "Saved views workflow"). Routed through the Next.js server proxy (see
// src/app/api/saved-views/**/route.ts), which forwards the caller's NextAuth
// session as a bearer token - same reasoning as dashboard/preferences. A
// missing/expired session surfaces as AdminAuthRequiredError (fetchAdminJson's
// naming - it's the generic "same-origin proxy" error, not admin-token
// specific), which SavedViewBar catches to render a "sign in" prompt instead
// of a hard failure.

export type SavedViewScope = "collector" | "admin" | "analytics" | "market";
export type SavedViewDensity = "compact" | "comfortable";

export interface SavedView {
  id: number;
  created_at: string;
  updated_at: string;
  name: string;
  description: string | null;
  route_path: string;
  view_type: string;
  scope: SavedViewScope;
  filters_json: Record<string, unknown> | null;
  sort_json: Record<string, unknown> | null;
  columns_json: Record<string, unknown> | null;
  density: SavedViewDensity;
  is_default: boolean;
  pinned: boolean;
  last_used_at: string | null;
  usage_count: number;
  notes: string | null;
}

export interface SavedViewListResponse {
  items: SavedView[];
  pagination: {
    total: number;
    limit: number;
    offset: number;
    has_next: boolean;
    has_previous: boolean;
    next_offset: number | null;
    previous_offset: number | null;
  };
}

export interface SavedViewCreateInput {
  name: string;
  description?: string | null;
  route_path: string;
  view_type: string;
  scope?: SavedViewScope;
  filters_json?: Record<string, unknown> | null;
  sort_json?: Record<string, unknown> | null;
  columns_json?: Record<string, unknown> | null;
  density?: SavedViewDensity;
  is_default?: boolean;
  pinned?: boolean;
  notes?: string | null;
}

export type SavedViewUpdateInput = Partial<
  Pick<
    SavedViewCreateInput,
    | "name"
    | "description"
    | "filters_json"
    | "sort_json"
    | "columns_json"
    | "density"
    | "is_default"
    | "pinned"
    | "notes"
  >
>;

export interface SavedViewQuery {
  route_path?: string;
  view_type?: string;
  scope?: SavedViewScope;
  pinned?: boolean;
  is_default?: boolean;
  q?: string;
  limit?: number;
  offset?: number;
}

function savedViewsQueryString(query?: SavedViewQuery): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export function fetchSavedViews(query?: SavedViewQuery): Promise<SavedViewListResponse> {
  return fetchAdminJson<SavedViewListResponse>(`/api/saved-views${savedViewsQueryString(query)}`);
}

export function getSavedView(id: number): Promise<SavedView> {
  return fetchAdminJson<SavedView>(`/api/saved-views/${id}`);
}

export function createSavedView(body: SavedViewCreateInput): Promise<SavedView> {
  return fetchAdminJson<SavedView>("/api/saved-views", { method: "POST", body });
}

export function updateSavedView(id: number, body: SavedViewUpdateInput): Promise<SavedView> {
  return fetchAdminJson<SavedView>(`/api/saved-views/${id}`, { method: "PATCH", body });
}

export function deleteSavedView(id: number): Promise<void> {
  return fetchAdminJson<void>(`/api/saved-views/${id}`, { method: "DELETE" });
}

export function markSavedViewUsed(id: number): Promise<SavedView> {
  return fetchAdminJson<SavedView>(`/api/saved-views/${id}/use`, { method: "POST" });
}

export function setDefaultSavedView(id: number): Promise<SavedView> {
  return fetchAdminJson<SavedView>(`/api/saved-views/${id}/set-default`, { method: "POST" });
}

export function clearDefaultSavedView(routePath: string, viewType: string): Promise<void> {
  return fetchAdminJson<void>("/api/saved-views/clear-default", {
    method: "POST",
    body: { route_path: routePath, view_type: viewType },
  });
}
