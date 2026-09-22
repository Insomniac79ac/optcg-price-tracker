import type {
  ProposalReviewAlternative,
  ProposalReviewGroup,
  ProposalReviewGroupDetail,
  ProposalReviewGroupList,
  ProposalReviewReleaseList,
  ProposalReviewSummary,
} from "@/lib/proposalReview";

export const REVIEW_SUMMARY: ProposalReviewSummary = {
  contract: { authority: "persisted_proposals" },
  total_current_groups: 4027,
  total_current_alternatives: 6149,
  pending_groups: 4027,
  approved_groups: 0,
  rejected_groups: 0,
  resulting_mappings_populated: 0,
  superseded_historical_groups: 0,
  by_resolution: {
    exact: 1918,
    ambiguous: 1866,
    unresolved_identity: 220,
    release_unresolved: 23,
    conflict: 0,
    stale: 0,
    superseded: 0,
  },
  by_source: {
    yuyutei: {
      total_current_groups: 3553,
      total_current_alternatives: 5300,
      resolutions: { exact: 1700, ambiguous: 1650, unresolved_identity: 190, release_unresolved: 13, conflict: 0, stale: 0, superseded: 0 },
    },
    snkrdunk: {
      total_current_groups: 474,
      total_current_alternatives: 849,
      resolutions: { exact: 218, ambiguous: 216, unresolved_identity: 30, release_unresolved: 10, conflict: 0, stale: 0, superseded: 0 },
    },
  },
  by_source_and_resolution: {},
  groups_with_one_alternative: 1918,
  groups_with_multiple_alternatives: 1866,
  maximum_alternatives_on_one_listing: 5,
  release_resolved_groups: 4004,
  null_release_groups: 23,
  groups_with_candidate_images: 3900,
  groups_with_no_candidate_image: 127,
  groups_with_recommended_alternatives: 1918,
  groups_with_no_recommended_alternative: 2109,
};

export const REVIEW_RELEASES: ProposalReviewReleaseList = {
  contract: { chronology_available: false, release_membership: "card_prints.release_product_id" },
  items: [
    {
      release_product_id: 17,
      official_code: "OP-17",
      display_name: "The New Emperor",
      source_catalogue: "bandai",
      authoritative_release_order: null,
      chronology_available: false,
      total_active_verified_japanese_card_prints: 120,
      existing_exact_source_card_mappings: 22,
      pending_proposal_groups: 315,
      exact_pending_groups: 150,
      ambiguous_pending_groups: 150,
      unresolved_identity_pending_groups: 15,
      release_unresolved_pending_groups: 0,
      alternatives: 490,
      remaining_prints_with_no_approved_mapping_after_exact_proposals: 45,
      sources: {
        yuyutei: { pending_proposal_groups: 275, exact_pending_groups: 130, ambiguous_pending_groups: 132, unresolved_identity_pending_groups: 13, release_unresolved_pending_groups: 0, alternatives: 430 },
        snkrdunk: { pending_proposal_groups: 40, exact_pending_groups: 20, ambiguous_pending_groups: 18, unresolved_identity_pending_groups: 2, release_unresolved_pending_groups: 0, alternatives: 60 },
      },
    },
    {
      release_product_id: null,
      official_code: null,
      display_name: "Unresolved release",
      source_catalogue: null,
      authoritative_release_order: null,
      chronology_available: false,
      total_active_verified_japanese_card_prints: 0,
      existing_exact_source_card_mappings: 0,
      pending_proposal_groups: 23,
      exact_pending_groups: 0,
      ambiguous_pending_groups: 0,
      unresolved_identity_pending_groups: 0,
      release_unresolved_pending_groups: 23,
      alternatives: 23,
      remaining_prints_with_no_approved_mapping_after_exact_proposals: 0,
      sources: {},
    },
  ],
};

const release = {
  id: 17,
  official_code: "OP-17",
  display_name: "The New Emperor",
  source_catalogue: "bandai",
  source_series_id: "series-op",
  source_url: "https://www.onepiece-cardgame.com/products/boosters/op17.php",
  verification_status: "verified",
  authoritative_release_order: null,
  chronology_available: false,
  membership_explanation: "Release membership is authoritative from CardPrint.release_product_id.",
};

const canonical = {
  id: 101,
  card_code: "OP01-001",
  name_en: "Roronoa Zoro",
  name_jp: "ロロノア・ゾロ",
  card_type: "CHARACTER",
  canonical_rarity: "SR",
};

const print = {
  alternative_id: 9001,
  card_print_id: 501,
  recommended: true,
  canonical_card: canonical,
  release,
  language: "ja",
  official_asset_variant: "p2",
  release_product_code: "OP-17",
  treatment: "parallel",
  official_rarity: "SR",
  official_block_icon: "2",
  official_name: "Roronoa Zoro",
  official_effect_text: "Fixture effect",
  artwork_key: "OP01-001_p2",
  artist: "Fixture Artist",
  printing_label: "Parallel art",
  special_print_label: "Anniversary treatment",
  canonical_image_url: "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001_p2.png",
  display_image: {
    url: "https://assets.atlas.test/owned/OP01-001_p2.webp",
    source: "bandai",
    exact_print_verified: true,
    owned_asset_selected: true,
    geometry: null,
  },
  image_missing: false,
  is_active: true,
  verification_status: "verified",
};

export function makeReviewGroup(overrides: Partial<ProposalReviewGroup> = {}): ProposalReviewGroup {
  return {
    id: 1127,
    source_id: 1,
    source_name: "yuyutei",
    source: { id: 1, name: "yuyutei" },
    canonical_source_listing_identity: "yuyutei:op17:9911",
    source_url: "https://yuyu-tei.jp/sell/opc/card/op17/9911",
    source_candidate_type: "yuyutei_candidate",
    source_candidate_id: 9911,
    resolution_status: "exact",
    review_status: "pending",
    resolver_version: "source-mapping-v4",
    created_at: "2026-09-21T02:00:00Z",
    updated_at: "2026-09-21T02:00:00Z",
    superseded_at: null,
    resulting_source_card_mapping_id: null,
    alternative_count: 1,
    recommended_alternative_count: 1,
    canonical_card_id: canonical.id,
    card_code: canonical.card_code,
    name_en: canonical.name_en,
    name_jp: canonical.name_jp,
    canonical_card: canonical,
    release_product_id: release.id,
    release,
    candidate: {
      candidate_type: "yuyutei_candidate",
      candidate_id: 9911,
      source_url: "https://yuyu-tei.jp/sell/opc/card/op17/9911",
      source_native_identity: "op17/9911",
      detected_card_code: "OP01-001",
      detected_rarity: "SR",
      image_url: "https://card.yuyu-tei.jp/card_image/opc/front/9911.jpg",
      image_missing: false,
      price_jpy: 3200,
      candidate_missing: false,
      yuyutei: { set_slug: "op17", product_id: "9911", name_jp: "ロロノア・ゾロ", availability: "in_stock", price_jpy: 3200, image_url: "https://card.yuyu-tei.jp/card_image/opc/front/9911.jpg" },
      snkrdunk: null,
    },
    recommended_print: print,
    ...overrides,
  };
}

export function makeAlternative(overrides: Partial<ProposalReviewAlternative> = {}): ProposalReviewAlternative {
  return {
    ...print,
    proposal_group_id: 1127,
    review_disposition: "pending",
    review_notes: null,
    reviewed_at: null,
    created_at: "2026-09-21T02:00:00Z",
    updated_at: "2026-09-21T02:00:00Z",
    supporting_evidence: ["Exact stored card code", { release_product_id: 17 }],
    missing_evidence: [],
    conflict_reasons: [],
    ...overrides,
  };
}

export function makeGroupList(items: ProposalReviewGroup[] = [makeReviewGroup()], total = items.length): ProposalReviewGroupList {
  return {
    contract: { authority: "persisted_proposals" },
    items,
    pagination: { total, limit: 50, offset: 0, has_next: total > 50, has_previous: false, next_offset: total > 50 ? 50 : null, previous_offset: null },
  };
}

export function makeReviewDetail(overrides: Partial<ProposalReviewGroupDetail> = {}): ProposalReviewGroupDetail {
  const group = makeReviewGroup();
  return {
    ...group,
    evidence_digest: "a".repeat(64),
    reviewed_at: null,
    reviewed_by: null,
    review_notes: null,
    selected_alternative_id: null,
    decision_basis_updated_at: null,
    evidence_summary: { candidate_id: 9911, matched_card_code: "OP01-001", release_product_id: 17 },
    resolution_reasons: ["Stored card code and release evidence support one exact printing."],
    resulting_mapping: null,
    candidate: {
      ...group.candidate,
      raw_listing_text: "OP01-001 ロロノア・ゾロ SR",
      normalized_title: "OP01-001 ロロノア ゾロ SR",
      match_status: "suggested",
      match_explanation: { positive: ["exact card code"], negative: [] },
      ambiguous_matches: null,
      stored_evidence: { card_code: "OP01-001", product_label: "OP17" },
      discovery_run: { id: 77, source: "yuyutei", status: "completed", started_at: "2026-09-20T01:00:00Z", finished_at: "2026-09-20T01:05:00Z", provenance: { snapshot_id: 700 } },
    },
    alternatives: [makeAlternative()],
    compatibility: {
      role: "Legacy Card/card_id compatibility only",
      candidate_matched_card_id: 45,
      candidate_best_match_card_id: 45,
      resulting_mapping_card_id: null,
      legacy_cards: [{ id: 45, card_code: "OP01-001", name_en: "Roronoa Zoro", name_jp: "ロロノア・ゾロ", set_code: "OP01", rarity: "SR", variant: "parallel", language: "jp" }],
    },
    historical_state: { current: true, superseded: false },
    ...overrides,
  };
}
