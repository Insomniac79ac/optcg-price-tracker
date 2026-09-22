import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({ getSession: vi.fn() }));

import { approveExactProposal, fetchProposalReviewGroups } from "./proposalReview";
import {
  DEFAULT_PROPOSAL_REVIEW_STATE,
  parseProposalReviewQueueState,
  proposalReviewQueueHref,
  safeProposalReviewReturnTo,
} from "./proposalReviewUrl";

describe("proposal review API client", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("forwards every supported persisted-list filter", async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response('{"items":[],"pagination":{"total":0,"limit":25,"offset":50,"has_next":false,"has_previous":true,"next_offset":null,"previous_offset":25},"contract":{}}'));
    await fetchProposalReviewGroups({
      source: "snkrdunk",
      release_product_id: 17,
      release_code: "OP-17",
      unresolved_release: true,
      resolution_status: "ambiguous",
      review_status: "pending",
      card_code: "OP01-001",
      candidate_id: 44,
      proposal_group_id: 55,
      has_candidate_image: false,
      has_recommended_alternative: true,
      include_superseded: true,
      q: "zoro",
      sort: "id_desc",
      limit: 25,
      offset: 50,
    });
    const requested = new URL(String(vi.mocked(global.fetch).mock.calls[0][0]), "http://localhost");
    expect(Object.fromEntries(requested.searchParams)).toEqual({
      source: "snkrdunk", release_product_id: "17", release_code: "OP-17", unresolved_release: "true",
      resolution_status: "ambiguous", review_status: "pending", card_code: "OP01-001", candidate_id: "44",
      proposal_group_id: "55", has_candidate_image: "false", has_recommended_alternative: "true",
      include_superseded: "true", q: "zoro", sort: "id_desc", limit: "25", offset: "50",
    });
  });

  it("posts the exact typed decision to the same-origin proxy without credential headers", async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      proposal_group_id: 42,
      review_status: "approved",
      selected_alternative_id: 7,
      card_print_id: 9,
    })));
    const request = {
      selected_alternative_id: 7,
      expected_evidence_digest: "a".repeat(64),
      expected_resolver_version: "source-mapping-v4",
      expected_updated_at: "2026-09-22T00:00:00.123456Z",
      review_note: "checked",
    };
    await approveExactProposal(42, request);
    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [path, init] = vi.mocked(global.fetch).mock.calls[0];
    expect(path).toBe("/api/admin/source-mapping-proposals/review/groups/42/approve-exact");
    expect(init).toMatchObject({ method: "POST", cache: "no-store", body: JSON.stringify(request) });
    expect(init?.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.stringify(init)).not.toMatch(/ADMIN_TOKEN|actor.assertion|reviewed_by/i);
  });

  it("preserves backend status, code, reason, and payload without retrying", async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: { code: "existing_mapping_was_rejected", message: "The stored mapping was rejected." },
    }), { status: 409 }));
    const promise = approveExactProposal(42, {
      selected_alternative_id: 7,
      expected_evidence_digest: "a".repeat(64),
      expected_resolver_version: "source-mapping-v4",
      expected_updated_at: "2026-09-22T00:00:00Z",
    });
    await expect(promise).rejects.toMatchObject({
      status: 409,
      code: "existing_mapping_was_rejected",
      message: "The stored mapping was rejected.",
      payload: { detail: { code: "existing_mapping_was_rejected", message: "The stored mapping was rejected." } },
    });
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it("marks a transport failure uncertain and never retries", async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError("offline"));
    await expect(approveExactProposal(42, {
      selected_alternative_id: 7,
      expected_evidence_digest: "a".repeat(64),
      expected_resolver_version: "source-mapping-v4",
      expected_updated_at: "2026-09-22T00:00:00Z",
    })).rejects.toMatchObject({ status: 0, code: "network_error", uncertain: true });
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });
});

describe("proposal review URL state", () => {
  it("recovers invalid values to safe defaults", () => {
    const state = parseProposalReviewQueueState(new URLSearchParams("source=bad&resolution=magic&page=nope&limit=500&candidateId=-5"));
    expect(state).toEqual(DEFAULT_PROPOSAL_REVIEW_STATE);
  });

  it("omits defaults and preserves meaningful queue state", () => {
    expect(proposalReviewQueueHref(DEFAULT_PROPOSAL_REVIEW_STATE)).toBe("/admin/source-mapping-proposals");
    expect(proposalReviewQueueHref({ ...DEFAULT_PROPOSAL_REVIEW_STATE, source: "yuyutei", page: 3, limit: 100 })).toBe("/admin/source-mapping-proposals?source=yuyutei&page=3&limit=100");
  });

  it("accepts only internal proposal-review return URLs", () => {
    expect(safeProposalReviewReturnTo("/admin/source-mapping-proposals?source=yuyutei&page=2")).toContain("page=2");
    expect(safeProposalReviewReturnTo("https://attacker.test")).toBe("/admin/source-mapping-proposals");
  });
});
