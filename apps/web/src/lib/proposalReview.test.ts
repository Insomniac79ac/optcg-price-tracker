import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({ getSession: vi.fn() }));

import { fetchProposalReviewGroups } from "./proposalReview";
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
