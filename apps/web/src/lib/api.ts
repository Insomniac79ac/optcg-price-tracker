
// The approval screen shows the same artwork the public catalogue does, so
// it reuses the catalogue's display-image contract rather than restating it.
import type { PrintDisplayImage } from "@/lib/prints";

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
  // Catalog-enrichment fields - nullable, most existing rows predate this
  // metadata being collected (see app.services.card_catalog_import).
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

/** One normalized Market Index source reference - see
 * services/api/app/services/market_index.py. Deliberately not a fixed
 * yuyutei_price/snkrdunk_price pair: `source`/`reference_type` name what
 * kind of value this is, so a future Cardrush/Mercado resolver needs no
 * frontend contract change. */
export interface MarketIndexSourceValue {
  source: string;
  reference_type: string;
  evidence_type: "listing" | "transaction";
  value_jpy: number | null;
  observed_at: string | null;
  sample_size: number | null;
  stale: boolean;
  eligible: boolean;
  fallback_used: boolean;
  ineligible_reason: string | null;
  /** Why this value may not mean what its number says - see
   * app.services.source_semantics and @/lib/sourceConstraint, which owns the
   * collector-facing wording. Optional because an API older than the
   * source-semantics release omits the field entirely; absent and null are
   * both "nothing to say about this value". Never rendered raw. */
  constraint?: string | null;
}

export interface MarketIndex {
  card_id: number;
  index_version: number;
  /** Which source-normalisation ruleset produced this index (see
   * app.services.source_semantics.SOURCE_SEMANTICS_VERSION). Debug/
   * reproducibility metadata only - deliberately never shown to collectors.
   * Optional for the same backward-compatibility reason as `constraint`. */
  source_semantics_version?: number;
  index_value_jpy: number | null;
  calculation_method: string;
  source_count: number;
  coverage_status: "full" | "limited" | "none";
  confidence: "high" | "medium" | "low";
  source_values: MarketIndexSourceValue[];
  auxiliary_values: MarketIndexSourceValue[];
  freshest_observation_at: string | null;
  stalest_eligible_source_at: string | null;
  stale_sources: string[];
  calculated_at: string;
}

export interface CardCatalogueItem extends Card {
  market_index: MarketIndex;
}

export interface CardCatalogueFacets {
  set_codes: string[];
  rarities: string[];
  languages: string[];
  variants: string[];
}

export interface CardCatalogueList {
  items: CardCatalogueItem[];
  total: number;
  limit: number;
  offset: number;
  pagination: PaginationMeta;
  facets: CardCatalogueFacets;
}

export type CardCatalogueSort = "card_code" | "name" | "index_desc" | "index_asc" | "updated";

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

/** One printing the listing could be describing.
 *
 * Everything here is a fact a collector would recognise on a tile - artwork,
 * names, product, printing - because that is what the operator is actually
 * comparing. `card_print_id` is what the approval call must send, not what
 * the operator reads. */
export interface ApprovalPrintOption {
  card_print_id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  display_image: PrintDisplayImage | null;
  image_url: string | null;
  found_in_product: string | null;
  rarity: string | null;
  special_print: string | null;
  printing: string | null;
  art_ordinal: number | null;
  language: string;
  approvable: boolean;
  refusal_code: string | null;
  refusal_detail: string | null;
}

export interface ApprovalSourceCandidate {
  candidate_id: number;
  source: string;
  title: string | null;
  source_url: string;
  source_image_url: string | null;
  detected_card_code: string | null;
  detected_set_code: string | null;
  detected_variant: string | null;
  detected_rarity: string | null;
  price_jpy: number | null;
}

/** Advisory artwork evidence, fetched only when an operator asks for it.
 *
 * `advisory_only` is in the payload rather than assumed: this must never be
 * rendered as a decision. There is no confidence score by design - the
 * validation showed a single number would overstate what the image proves. */
export interface ArtworkPreview {
  status: "exact" | "ambiguous" | "no_match" | "unusable";
  summary: string;
  method_version: string;
  listing_image_url: string | null;
  considered_card_print_ids: number[];
  winning_card_print_ids: number[];
  /** True when the matched artwork belongs to more than one printing (a
   * reprint). No image can separate those. */
  winning_class_is_shared: boolean;
  corroborates_card_print_id: number | null;
  best_score: number | null;
  runner_up_score: number | null;
  margin: number | null;
  detail: string | null;
  fetch_errors: string[];
  advisory_only: boolean;
}

export interface ApprovalContext {
  candidate: ApprovalSourceCandidate;
  options: ApprovalPrintOption[];
  /** Set only when exactly one option is approvable. Pre-selects; never
   * auto-approves. */
  resolvable_card_print_id: number | null;
  ambiguity_reason: string | null;
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

export interface CollectionAttempt {
  id: number;
  batch_run_id: string;
  selection_ordinal: number;
  source_id: number;
  source_name: string | null;
  source_card_mapping_id: number;
  /** False when the mapping this attempt referred to can no longer be found.
   * The stored ids stay authoritative; the card fields go null rather than
   * the API inventing an identity for it. */
  mapping_resolved: boolean;
  card_print_id: number | null;
  card_code: string | null;
  selected_at: string;
  started_at: string | null;
  finished_at: string | null;
  /** Derived server-side from started_at/finished_at - null for an attempt
   * that never started (skipped) or has not finished (in flight). */
  duration_seconds: number | null;
  status: string;
  failure_stage: string | null;
  failure_reason: string | null;
  source_denied: boolean;
  price_observation_id: number | null;
}

export interface CollectionAttemptSummary {
  total_attempts: number;
  started: number;
  written: number;
  skipped: number;
  source_denied: number;
  still_selected: number;
  by_status: Record<string, number>;
  by_failure_stage: Record<string, number>;
  earliest_selected_at: string | null;
  latest_finished_at: string | null;
}

export interface CollectionAttemptList {
  summary: CollectionAttemptSummary;
  attempts: CollectionAttempt[];
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

// No longer attaches anything - admin auth for every /api/admin/** proxy
// route is now the browser's Auth.js session cookie (sent automatically on
// same-origin fetch) plus a server-side-injected ADMIN_TOKEN the browser
// never sees (see src/lib/adminProxy.ts). Kept as a no-op rather than
// removed at each of its call sites below so a 401 still surfaces as
// AdminAuthRequiredError exactly as before, distinguishing "not an admin
// session" from other failures.
function adminHeaders(): Record<string, string> {
  return {};
}

const ADMIN_FETCH_TIMEOUT_MS = 15_000;

/** Fetches a relative (same-origin) admin path - e.g. a Next.js API proxy
 * route - relying on the browser's Auth.js session cookie for auth (sent
 * automatically on a same-origin fetch; see adminHeaders() above).
 * Distinguishes 401/404/timeout/network failures so callers can render a
 * state more specific than a generic error.
 *
 * Defaults to GET; pass `options.method`/`options.body` for mutations
 * (POST/PATCH) through the same proxy-aware error handling. */
export async function fetchAdminJson<T>(
  path: string,
  options?: { method?: string; body?: unknown; signal?: AbortSignal },
): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, ADMIN_FETCH_TIMEOUT_MS);
  const abortFromCaller = () => controller.abort();
  if (options?.signal?.aborted) controller.abort();
  else options?.signal?.addEventListener("abort", abortFromCaller, { once: true });

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
      if (!timedOut && options?.signal?.aborted) throw err;
      throw new AdminTimeoutError();
    }
    throw new AdminNetworkError(
      err instanceof Error ? err.message : "Network error",
    );
  } finally {
    clearTimeout(timeout);
    options?.signal?.removeEventListener("abort", abortFromCaller);
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

export type QueryValue = string | number | boolean | readonly (string | number | boolean)[] | null | undefined;

export function buildQueryString(
  params?: Record<string, QueryValue>,
): string {
  if (!params) return "";
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue;
    if (Array.isArray(value)) value.forEach((entry) => query.append(key, String(entry)));
    else query.set(key, String(value));
  }
  const qs = query.toString();
  return qs ? `?${qs}` : "";
}

export interface ApiRequestOptions {
  /** Query params - null/undefined values are omitted, everything else is
   * stringified (so booleans/numbers don't need manual String() calls). */
  params?: Record<string, QueryValue>;
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
 * resource instead. */
export function apiDelete<T = void>(path: string, options?: ApiRequestOptions): Promise<T> {
  return _apiRequest<T>("DELETE", path, options);
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

export function fetchCardMarketIndex(id: string | number): Promise<MarketIndex> {
  return apiGet<MarketIndex>(`/cards/${id}/market-index`);
}

/** The batch-compatible mechanism the public /cards catalogue grid uses -
 * one request for a whole page of cards, each already carrying its Market
 * Index, rather than one request per card (see
 * services/api/app/services/market_index.py's "Batch-safe by
 * construction"). */
export function fetchCardsCatalogue(params?: {
  q?: string;
  set_code?: string;
  rarity?: string;
  language?: string;
  variant?: string;
  sort?: CardCatalogueSort;
  limit?: number;
  offset?: number;
}): Promise<CardCatalogueList> {
  return apiGet<CardCatalogueList>("/cards/catalogue", { params });
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
  // Via the Next.js proxy, not apiGet direct-to-backend - see
  // fetchRefreshRuns above for why.
  return fetchAdminJson<SnkrdunkCandidateList>(
    `/api/admin/snkrdunk-candidates${qs ? `?${qs}` : ""}`,
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

/** The operator's decision aid: the listing on one side, and every printing
 * that shares its card code on the other, each saying whether the stored
 * evidence can justify approving it. */
export function fetchCandidatePrintOptions(
  candidateId: number,
): Promise<ApprovalContext> {
  return fetchAdminJson<ApprovalContext>(
    `/api/admin/snkrdunk-candidates/${candidateId}/print-options`,
  );
}

/** Advisory only, and deliberately a separate call an operator triggers.
 *
 * It makes the server fetch the marketplace photo and the official artwork
 * for every sibling printing, so it must not run on page load - browsing the
 * candidate queue would otherwise depend on third-party latency. Nothing it
 * returns affects approval. */
export function fetchCandidateArtworkPreview(
  candidateId: number,
): Promise<ArtworkPreview> {
  return fetchAdminJson<ArtworkPreview>(
    `/api/admin/snkrdunk-candidates/${candidateId}/artwork-preview`,
    { method: "POST" },
  );
}

/** `cardPrintId` is required by the API, not optional here for convenience:
 * a mapping is a claim about which printing was priced, and the approval is
 * refused outright when the source evidence cannot single that printing out. */
export function approveCandidateMatch(
  candidateId: number,
  cardId: number,
  cardPrintId: number,
  reviewNotes?: string,
): Promise<SnkrdunkCandidate> {
  return fetchAdminJson<SnkrdunkCandidate>(
    `/api/admin/snkrdunk-candidates/${candidateId}/approve-match`,
    {
      method: "POST",
      body: {
        card_id: cardId,
        card_print_id: cardPrintId,
        review_notes: reviewNotes ?? null,
      },
    },
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

export interface SourceCardMapping {
  id: number;
  card_id: number;
  card_code: string | null;
  name_en: string | null;
  name_jp: string | null;
  source_name: string | null;
  source_url: string | null;
  source_card_id: string;
  manual_verified: boolean;
  match_confidence: number | null;
  match_confidence_label: string | null;
  last_match_checked_at: string | null;
  is_active: boolean;
  review_status: string;
  review_notes: string | null;
  created_at: string;
  updated_at: string;
  last_verified_at: string | null;
}

export interface SourceCardMappingList {
  items: SourceCardMapping[];
  total: number;
  limit: number;
  offset: number;
  pagination: PaginationMeta;
}

/** Routed through the Next.js server proxy (see
 * src/app/api/admin/source-mappings/route.ts) - the plain mapping list (not
 * the /quality review view), used by the card detail page's admin-only
 * source-mappings mini panel. */
export function fetchAdminSourceMappings(params?: {
  source?: string;
  review_status?: string;
  is_active?: boolean;
  card_code?: string;
  limit?: number;
  offset?: number;
}): Promise<SourceCardMappingList> {
  const query = new URLSearchParams();
  if (params?.source) query.set("source", params.source);
  if (params?.review_status) query.set("review_status", params.review_status);
  if (params?.is_active !== undefined) query.set("is_active", String(params.is_active));
  if (params?.card_code) query.set("card_code", params.card_code);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return fetchAdminJson<SourceCardMappingList>(`/api/admin/source-mappings${qs ? `?${qs}` : ""}`);
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
  // Via the Next.js proxy (session-authorized, server-side ADMIN_TOKEN
  // injection - see src/lib/adminProxy.ts), not apiGet direct-to-backend:
  // this is an /admin/* route requiring X-Admin-Token, which the browser
  // no longer holds (see the removal of the client-side admin token flow).
  return fetchAdminJson<PriceRefreshRunList>(
    `/api/admin/refresh-runs${qs ? `?${qs}` : ""}`,
  );
}

export function fetchRefreshRun(runId: number): Promise<PriceRefreshRun> {
  return fetchAdminJson<PriceRefreshRun>(`/api/admin/refresh-runs/${runId}`);
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
  return fetchAdminJson<AlertEventList>(`/api/admin/alert-events${qs ? `?${qs}` : ""}`);
}

export function fetchAlertEvent(eventId: number): Promise<AlertEvent> {
  return fetchAdminJson<AlertEvent>(`/api/admin/alert-events/${eventId}`);
}

export function fetchAlertRules(): Promise<AlertRule[]> {
  return fetchAdminJson<AlertRule[]>("/api/admin/alert-rules");
}

export function updateAlertRule(
  ruleId: number,
  body: { is_active?: boolean; threshold_pct?: number },
): Promise<AlertRule> {
  return fetchAdminJson<AlertRule>(`/api/admin/alert-rules/${ruleId}`, {
    method: "PATCH",
    body,
  });
}

function filenameFromContentDisposition(value: string | null): string | null {
  if (!value) return null;
  const match = /filename=([^;]+)/.exec(value);
  return match ? match[1].trim().replace(/^"|"$/g, "") : null;
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

export interface FullMarketRefreshRequest {
  source: string;
  limit?: number | null;
  dry_run?: boolean;
}

export interface FullMarketRefreshResponse {
  price_refresh_run_id: number | null;
  portfolio_snapshot_id: number | null;
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
 * src/app/api/admin/actions/full-market-refresh/route.ts). */
export function triggerFullMarketRefresh(
  body: FullMarketRefreshRequest,
): Promise<FullMarketRefreshResponse> {
  return fetchAdminJson<FullMarketRefreshResponse>("/api/admin/actions/full-market-refresh", {
    method: "POST",
    body,
  });
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

export function fetchCollectionAttempts(params?: {
  batch_run_id?: string;
  status?: string;
  failure_stage?: string;
  source_denied?: boolean;
  source_card_mapping_id?: number;
  limit?: number;
  offset?: number;
}): Promise<CollectionAttemptList> {
  const query = new URLSearchParams();
  if (params?.batch_run_id) query.set("batch_run_id", params.batch_run_id);
  if (params?.status) query.set("status", params.status);
  if (params?.failure_stage) query.set("failure_stage", params.failure_stage);
  if (params?.source_denied !== undefined) {
    query.set("source_denied", String(params.source_denied));
  }
  if (params?.source_card_mapping_id !== undefined) {
    query.set("source_card_mapping_id", String(params.source_card_mapping_id));
  }
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  // Goes through the Route Handler proxy, not the API directly - same reason
  // as fetchRefreshRuns: the admin token never reaches the browser.
  return fetchAdminJson<CollectionAttemptList>(
    `/api/admin/collection-attempts${qs ? `?${qs}` : ""}`,
  );
}
