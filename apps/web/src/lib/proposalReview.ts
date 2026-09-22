import { fetchAdminJson, type PaginationMeta } from "@/lib/api";

export type ProposalReviewJsonValue =
  | string
  | number
  | boolean
  | null
  | ProposalReviewJsonValue[]
  | { [key: string]: ProposalReviewJsonValue };

export type ProposalReviewResolution =
  | "exact"
  | "ambiguous"
  | "unresolved_identity"
  | "release_unresolved"
  | "conflict"
  | "stale"
  | "superseded";

export type ProposalReviewStatus = "pending" | "approved" | "rejected";
export type ProposalReviewSourceName = "yuyutei" | "snkrdunk";
export type ProposalReviewSort =
  | "default"
  | "id_asc"
  | "id_desc"
  | "created_newest"
  | "created_oldest"
  | "release_newest"
  | "release_oldest"
  | "exact_first"
  | "ambiguous_first"
  | "source"
  | "card_code";

export interface ProposalReviewResolutionCounts {
  exact: number;
  ambiguous: number;
  unresolved_identity: number;
  release_unresolved: number;
  conflict: number;
  stale: number;
  superseded: number;
}

export interface ProposalReviewSourceSummary {
  total_current_groups: number;
  total_current_alternatives: number;
  resolutions: ProposalReviewResolutionCounts;
}

export interface ProposalReviewSummary {
  contract: Record<string, ProposalReviewJsonValue>;
  total_current_groups: number;
  total_current_alternatives: number;
  pending_groups: number;
  approved_groups: number;
  rejected_groups: number;
  resulting_mappings_populated: number;
  superseded_historical_groups: number;
  by_resolution: ProposalReviewResolutionCounts;
  by_source: Record<string, ProposalReviewSourceSummary>;
  by_source_and_resolution: Record<string, ProposalReviewResolutionCounts>;
  groups_with_one_alternative: number;
  groups_with_multiple_alternatives: number;
  maximum_alternatives_on_one_listing: number;
  release_resolved_groups: number;
  null_release_groups: number;
  groups_with_candidate_images: number;
  groups_with_no_candidate_image: number;
  groups_with_recommended_alternatives: number;
  groups_with_no_recommended_alternative: number;
}

export interface ProposalReviewReleaseSource {
  pending_proposal_groups: number;
  exact_pending_groups: number;
  ambiguous_pending_groups: number;
  unresolved_identity_pending_groups: number;
  release_unresolved_pending_groups: number;
  alternatives: number;
}

export interface ProposalReviewRelease {
  release_product_id: number | null;
  official_code: string | null;
  display_name: string;
  source_catalogue: string | null;
  authoritative_release_order: string | null;
  chronology_available: boolean;
  total_active_verified_japanese_card_prints: number;
  existing_exact_source_card_mappings: number;
  pending_proposal_groups: number;
  exact_pending_groups: number;
  ambiguous_pending_groups: number;
  unresolved_identity_pending_groups: number;
  release_unresolved_pending_groups: number;
  alternatives: number;
  remaining_prints_with_no_approved_mapping_after_exact_proposals: number;
  sources: Record<string, ProposalReviewReleaseSource>;
}

export interface ProposalReviewReleaseList {
  contract: Record<string, ProposalReviewJsonValue>;
  items: ProposalReviewRelease[];
}

export interface ProposalReviewSource {
  id: number;
  name: string;
}

export interface ProposalReviewCanonicalCard {
  id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  card_type: string | null;
  canonical_rarity: string | null;
}

export interface ProposalReviewReleaseContext {
  id: number;
  official_code: string | null;
  display_name: string;
  source_catalogue: string;
  source_series_id: string;
  source_url: string;
  verification_status: string;
  authoritative_release_order: string | null;
  chronology_available: boolean;
  membership_explanation: string;
}

export interface ProposalReviewYuyuteiCandidate {
  set_slug: string;
  product_id: string;
  name_jp: string | null;
  availability: string | null;
  price_jpy: number | null;
  image_url: string | null;
}

export interface ProposalReviewSnkrdunkCandidate {
  title: string | null;
  listing_count: number | null;
  condition_label: string | null;
  price_jpy: number | null;
  detected_set_code: string | null;
  detected_variant: string | null;
  image_url: string | null;
}

export interface ProposalReviewCandidateSummary {
  candidate_type: string;
  candidate_id: number;
  source_url: string;
  source_native_identity: string;
  detected_card_code: string | null;
  detected_rarity: string | null;
  image_url: string | null;
  image_missing: boolean;
  price_jpy: number | null;
  candidate_missing: boolean;
  yuyutei: ProposalReviewYuyuteiCandidate | null;
  snkrdunk: ProposalReviewSnkrdunkCandidate | null;
}

export interface ProposalReviewDiscoveryRun {
  id: number;
  source: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  provenance: Record<string, ProposalReviewJsonValue>;
}

export interface ProposalReviewCandidateDetail extends ProposalReviewCandidateSummary {
  raw_listing_text: string | null;
  normalized_title: string | null;
  match_status: string | null;
  match_explanation: Record<string, ProposalReviewJsonValue> | null;
  ambiguous_matches: ProposalReviewJsonValue[] | null;
  stored_evidence: Record<string, ProposalReviewJsonValue>;
  discovery_run: ProposalReviewDiscoveryRun | null;
}

export interface ProposalReviewDisplayImage {
  url: string;
  source: string;
  exact_print_verified: boolean;
  owned_asset_selected: boolean;
  geometry: {
    canvas_px: { width: number; height: number };
    card_bbox_px: { x: number; y: number; width: number; height: number };
  } | null;
}

export interface ProposalReviewPrint {
  alternative_id: number;
  card_print_id: number;
  recommended: boolean;
  canonical_card: ProposalReviewCanonicalCard;
  release: ProposalReviewReleaseContext | null;
  language: string;
  official_asset_variant: string | null;
  release_product_code: string | null;
  treatment: string | null;
  official_rarity: string | null;
  official_block_icon: string | null;
  official_name: string | null;
  official_effect_text: string | null;
  artwork_key: string | null;
  artist: string | null;
  printing_label: string | null;
  special_print_label: string | null;
  canonical_image_url: string | null;
  display_image: ProposalReviewDisplayImage | null;
  image_missing: boolean;
  is_active: boolean;
  verification_status: string;
}

export interface ProposalReviewAlternative extends ProposalReviewPrint {
  proposal_group_id: number;
  review_disposition: string;
  review_notes: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
  supporting_evidence: ProposalReviewJsonValue[];
  missing_evidence: ProposalReviewJsonValue[];
  conflict_reasons: ProposalReviewJsonValue[];
}

export interface ProposalReviewLegacyCard {
  id: number;
  card_code: string;
  name_en: string | null;
  name_jp: string | null;
  set_code: string;
  rarity: string;
  variant: string | null;
  language: string;
}

export interface ProposalReviewCompatibility {
  role: string;
  candidate_matched_card_id: number | null;
  candidate_best_match_card_id: number | null;
  resulting_mapping_card_id: number | null;
  legacy_cards: ProposalReviewLegacyCard[];
}

export interface ProposalReviewGroup {
  id: number;
  source_id: number;
  source_name: string;
  source: ProposalReviewSource;
  canonical_source_listing_identity: string;
  source_url: string;
  source_candidate_type: string;
  source_candidate_id: number;
  resolution_status: ProposalReviewResolution | string;
  review_status: ProposalReviewStatus | string;
  resolver_version: string;
  created_at: string;
  updated_at: string;
  superseded_at: string | null;
  resulting_source_card_mapping_id: number | null;
  alternative_count: number;
  recommended_alternative_count: number;
  canonical_card_id: number | null;
  card_code: string | null;
  name_en: string | null;
  name_jp: string | null;
  canonical_card: ProposalReviewCanonicalCard | null;
  release_product_id: number | null;
  release: ProposalReviewReleaseContext | null;
  candidate: ProposalReviewCandidateSummary;
  recommended_print: ProposalReviewPrint | null;
}

export interface ProposalReviewGroupList {
  contract: Record<string, ProposalReviewJsonValue>;
  items: ProposalReviewGroup[];
  pagination: PaginationMeta;
}

export interface ProposalReviewGroupDetail extends ProposalReviewGroup {
  evidence_digest: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
  review_notes: string | null;
  selected_alternative_id: number | null;
  decision_basis_updated_at: string | null;
  evidence_summary: Record<string, ProposalReviewJsonValue>;
  resolution_reasons: ProposalReviewJsonValue[];
  resulting_mapping: Record<string, ProposalReviewJsonValue> | null;
  candidate: ProposalReviewCandidateDetail;
  alternatives: ProposalReviewAlternative[];
  compatibility: ProposalReviewCompatibility;
  historical_state: Record<string, ProposalReviewJsonValue>;
}

export interface ApproveExactProposalRequest {
  selected_alternative_id: number;
  expected_evidence_digest: string;
  expected_resolver_version: string;
  expected_updated_at: string;
  review_note?: string;
}

export interface ApproveExactProposalResponse {
  proposal_group_id: number;
  review_status: "approved";
  selected_alternative_id: number;
  resulting_source_card_mapping_id: number;
  card_print_id: number;
  source: ProposalReviewSourceName;
  source_candidate_id: number;
  reviewed_at: string;
  reviewed_by: string;
  review_notes: string | null;
  decision_basis_updated_at: string;
  mapping_created: boolean;
  mapping_reused: boolean;
  candidate_status: string;
  idempotent_replay: boolean;
  collection_triggered: boolean;
  price_observation_written: boolean;
  eligible_for_future_scheduled_collection: boolean;
}

export interface ProposalApprovalErrorPayload {
  detail?:
    | string
    | { code?: string; message?: string }
    | Array<Record<string, ProposalReviewJsonValue>>;
  error?: string;
  backend_status?: number;
}

export class ProposalApprovalError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly payload: ProposalApprovalErrorPayload | null;
  readonly uncertain: boolean;

  constructor({
    message,
    status,
    code = null,
    payload = null,
    uncertain = false,
  }: {
    message: string;
    status: number;
    code?: string | null;
    payload?: ProposalApprovalErrorPayload | null;
    uncertain?: boolean;
  }) {
    super(message);
    this.name = "ProposalApprovalError";
    this.status = status;
    this.code = code;
    this.payload = payload;
    this.uncertain = uncertain;
  }
}

export interface ApproveExactProposalOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

export interface ProposalReviewGroupParams {
  source?: ProposalReviewSourceName;
  release_product_id?: number;
  release_code?: string;
  unresolved_release?: boolean;
  resolution_status?: ProposalReviewResolution;
  review_status?: ProposalReviewStatus;
  card_code?: string;
  candidate_id?: number;
  proposal_group_id?: number;
  has_candidate_image?: boolean;
  has_recommended_alternative?: boolean;
  include_superseded?: boolean;
  q?: string;
  sort?: ProposalReviewSort;
  limit?: 25 | 50 | 100 | 200;
  offset?: number;
  signal?: AbortSignal;
}

function addParam(params: URLSearchParams, key: string, value: string | number | boolean | undefined) {
  if (value !== undefined) params.set(key, String(value));
}

export function fetchProposalReviewSummary(): Promise<ProposalReviewSummary> {
  return fetchAdminJson<ProposalReviewSummary>(
    "/api/admin/source-mapping-proposals/review/summary",
  );
}

export function fetchProposalReviewReleases(): Promise<ProposalReviewReleaseList> {
  return fetchAdminJson<ProposalReviewReleaseList>(
    "/api/admin/source-mapping-proposals/review/releases",
  );
}

export function fetchProposalReviewGroups(
  options: ProposalReviewGroupParams = {},
): Promise<ProposalReviewGroupList> {
  const params = new URLSearchParams();
  addParam(params, "source", options.source);
  addParam(params, "release_product_id", options.release_product_id);
  addParam(params, "release_code", options.release_code);
  addParam(params, "unresolved_release", options.unresolved_release || undefined);
  addParam(params, "resolution_status", options.resolution_status);
  addParam(params, "review_status", options.review_status);
  addParam(params, "card_code", options.card_code);
  addParam(params, "candidate_id", options.candidate_id);
  addParam(params, "proposal_group_id", options.proposal_group_id);
  addParam(params, "has_candidate_image", options.has_candidate_image);
  addParam(params, "has_recommended_alternative", options.has_recommended_alternative);
  addParam(params, "include_superseded", options.include_superseded || undefined);
  addParam(params, "q", options.q);
  addParam(params, "sort", options.sort && options.sort !== "default" ? options.sort : undefined);
  addParam(params, "limit", options.limit);
  addParam(params, "offset", options.offset);
  const query = params.toString();
  return fetchAdminJson<ProposalReviewGroupList>(
    `/api/admin/source-mapping-proposals/review/groups${query ? `?${query}` : ""}`,
    { signal: options.signal },
  );
}

export function fetchProposalReviewGroup(
  id: number,
  signal?: AbortSignal,
): Promise<ProposalReviewGroupDetail> {
  return fetchAdminJson<ProposalReviewGroupDetail>(
    `/api/admin/source-mapping-proposals/review/groups/${id}`,
    { signal },
  );
}

const APPROVAL_TIMEOUT_MS = 15_000;

/** Sends one deliberate exact-proposal decision through the same-origin
 * Next.js proxy. The browser knows neither server credential and this helper
 * never retries a mutation after any response or transport failure. */
export async function approveExactProposal(
  proposalGroupId: number,
  request: ApproveExactProposalRequest,
  options: ApproveExactProposalOptions = {},
): Promise<ApproveExactProposalResponse> {
  const path = `/api/admin/source-mapping-proposals/review/groups/${proposalGroupId}/approve-exact`;
  const controller = new AbortController();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, options.timeoutMs ?? APPROVAL_TIMEOUT_MS);
  const abortFromCaller = () => controller.abort();
  if (options.signal?.aborted) controller.abort();
  else options.signal?.addEventListener("abort", abortFromCaller, { once: true });

  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      if (!timedOut && options.signal?.aborted) throw error;
      throw new ProposalApprovalError({
        message: "The approval request timed out before its result was known.",
        status: 0,
        code: "request_timeout",
        uncertain: true,
      });
    }
    throw new ProposalApprovalError({
      message: error instanceof Error ? error.message : "Network error",
      status: 0,
      code: "network_error",
      uncertain: true,
    });
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener("abort", abortFromCaller);
  }

  const text = await response.text();
  let payload: ProposalApprovalErrorPayload | ApproveExactProposalResponse | null = null;
  if (text) {
    try {
      payload = JSON.parse(text) as ProposalApprovalErrorPayload | ApproveExactProposalResponse;
    } catch {
      throw new ProposalApprovalError({
        message: "The approval service returned an unreadable response.",
        status: response.status,
        code: "invalid_response",
        uncertain: response.ok || response.status >= 500,
      });
    }
  }

  if (!response.ok) {
    const errorPayload = payload as ProposalApprovalErrorPayload | null;
    const detail = errorPayload?.detail;
    const code = typeof detail === "object" && !Array.isArray(detail) ? detail?.code ?? null : null;
    const message =
      (typeof detail === "object" && !Array.isArray(detail) ? detail?.message : null) ??
      (typeof detail === "string" ? detail : null) ??
      errorPayload?.error ??
      `Approval failed with status ${response.status}.`;
    throw new ProposalApprovalError({
      message,
      status: response.status,
      code,
      payload: errorPayload,
      uncertain: response.status >= 500,
    });
  }
  if (!payload) {
    throw new ProposalApprovalError({
      message: "The approval service returned an empty response.",
      status: response.status,
      code: "invalid_response",
      uncertain: true,
    });
  }
  return payload as ApproveExactProposalResponse;
}
