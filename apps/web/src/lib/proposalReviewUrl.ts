import type {
  ProposalReviewResolution,
  ProposalReviewSort,
  ProposalReviewSourceName,
  ProposalReviewStatus,
} from "@/lib/proposalReview";

export const PROPOSAL_REVIEW_LIMITS = [25, 50, 100, 200] as const;
export type ProposalReviewLimit = (typeof PROPOSAL_REVIEW_LIMITS)[number];

export const PROPOSAL_REVIEW_SORTS: ProposalReviewSort[] = [
  "default",
  "id_asc",
  "id_desc",
  "created_newest",
  "created_oldest",
  "release_newest",
  "release_oldest",
  "exact_first",
  "ambiguous_first",
  "source",
  "card_code",
];

const SOURCES: ProposalReviewSourceName[] = ["yuyutei", "snkrdunk"];
const RESOLUTIONS: ProposalReviewResolution[] = [
  "exact",
  "ambiguous",
  "unresolved_identity",
  "release_unresolved",
  "conflict",
  "stale",
  "superseded",
];
const REVIEW_STATUSES: ProposalReviewStatus[] = ["pending", "approved", "rejected"];
const BOOLEAN_FILTERS = ["", "true", "false"] as const;

export interface ProposalReviewQueueState {
  source: "" | ProposalReviewSourceName;
  release: string;
  unresolvedRelease: boolean;
  resolution: "" | ProposalReviewResolution;
  reviewStatus: "" | ProposalReviewStatus;
  cardCode: string;
  candidateId: string;
  proposalId: string;
  hasImage: "" | "true" | "false";
  hasRecommended: "" | "true" | "false";
  includeSuperseded: boolean;
  q: string;
  sort: ProposalReviewSort;
  page: number;
  limit: ProposalReviewLimit;
}

export const DEFAULT_PROPOSAL_REVIEW_STATE: ProposalReviewQueueState = {
  source: "",
  release: "",
  unresolvedRelease: false,
  resolution: "",
  reviewStatus: "pending",
  cardCode: "",
  candidateId: "",
  proposalId: "",
  hasImage: "",
  hasRecommended: "",
  includeSuperseded: false,
  q: "",
  sort: "default",
  page: 1,
  limit: 50,
};

function oneOf<T extends string>(value: string | null, values: readonly T[], fallback: T): T {
  return value && values.includes(value as T) ? (value as T) : fallback;
}

function positiveInteger(value: string | null, fallback: number): number {
  if (!value || !/^\d+$/.test(value)) return fallback;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function idFilter(value: string | null): string {
  return value && /^\d+$/.test(value) && Number(value) > 0 ? value : "";
}

export function parseProposalReviewQueueState(
  params: Pick<URLSearchParams, "get">,
): ProposalReviewQueueState {
  const requestedLimit = positiveInteger(params.get("limit"), DEFAULT_PROPOSAL_REVIEW_STATE.limit);
  const limit = PROPOSAL_REVIEW_LIMITS.includes(requestedLimit as ProposalReviewLimit)
    ? (requestedLimit as ProposalReviewLimit)
    : DEFAULT_PROPOSAL_REVIEW_STATE.limit;
  return {
    source: oneOf(params.get("source"), ["", ...SOURCES], ""),
    release: idFilter(params.get("release")),
    unresolvedRelease: params.get("unresolvedRelease") === "true",
    resolution: oneOf(params.get("resolution"), ["", ...RESOLUTIONS], ""),
    reviewStatus: oneOf(
      params.get("reviewStatus"),
      ["", ...REVIEW_STATUSES],
      DEFAULT_PROPOSAL_REVIEW_STATE.reviewStatus,
    ),
    cardCode: params.get("cardCode")?.trim() ?? "",
    candidateId: idFilter(params.get("candidateId")),
    proposalId: idFilter(params.get("proposalId")),
    hasImage: oneOf(params.get("hasImage"), BOOLEAN_FILTERS, ""),
    hasRecommended: oneOf(params.get("hasRecommended"), BOOLEAN_FILTERS, ""),
    includeSuperseded: params.get("includeSuperseded") === "true",
    q: params.get("q")?.trim() ?? "",
    sort: oneOf(params.get("sort"), PROPOSAL_REVIEW_SORTS, "default"),
    page: positiveInteger(params.get("page"), 1),
    limit,
  };
}

export function proposalReviewStateParams(state: ProposalReviewQueueState): URLSearchParams {
  const params = new URLSearchParams();
  if (state.source) params.set("source", state.source);
  if (state.release) params.set("release", state.release);
  if (state.unresolvedRelease) params.set("unresolvedRelease", "true");
  if (state.resolution) params.set("resolution", state.resolution);
  if (state.reviewStatus !== DEFAULT_PROPOSAL_REVIEW_STATE.reviewStatus) {
    params.set("reviewStatus", state.reviewStatus);
  }
  if (state.cardCode) params.set("cardCode", state.cardCode);
  if (state.candidateId) params.set("candidateId", state.candidateId);
  if (state.proposalId) params.set("proposalId", state.proposalId);
  if (state.hasImage) params.set("hasImage", state.hasImage);
  if (state.hasRecommended) params.set("hasRecommended", state.hasRecommended);
  if (state.includeSuperseded) params.set("includeSuperseded", "true");
  if (state.q) params.set("q", state.q);
  if (state.sort !== "default") params.set("sort", state.sort);
  if (state.page !== 1) params.set("page", String(state.page));
  if (state.limit !== DEFAULT_PROPOSAL_REVIEW_STATE.limit) params.set("limit", String(state.limit));
  return params;
}

export function proposalReviewQueueHref(state: ProposalReviewQueueState): string {
  const query = proposalReviewStateParams(state).toString();
  return `/admin/source-mapping-proposals${query ? `?${query}` : ""}`;
}

export function safeProposalReviewReturnTo(value: string | null): string {
  const queuePath = "/admin/source-mapping-proposals";
  if (!value) return queuePath;
  if (value !== queuePath && !value.startsWith(`${queuePath}?`)) return queuePath;
  if (value.startsWith("//") || value.includes("\n") || value.includes("\r")) {
    return queuePath;
  }
  return value;
}
