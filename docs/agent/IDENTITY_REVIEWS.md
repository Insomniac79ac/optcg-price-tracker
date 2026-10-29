# Physical artwork reviews (Yuyu-Tei ambiguous listings)

A Yuyu-Tei listing whose card code has several prints in its release (base, parallels) is
`ambiguous`: no rule can say which print it sells. It becomes exact only through an attributable
visual review of retained bytes, recorded in
`services/api/app/services/evidence/positive_physical_artwork.json` and validated on every
resolver run by `app.services.physical_artwork_proof` (staging only).

## Pipeline

1. **Capture** (`enqueue-capture-batch`, owner-approved dry run then apply): the Yuyu-Tei
   collector retains the product page, the listing's image and every sibling's official image
   (`identity_evidence.capture_pages`). Nothing is decided.
2. **Review pack** (`ops-readonly` `db-diagnostic identity-capture-work`, statement
   `review_pack`): each completed capture still ambiguous, with its lineage.
3. **Visual review**: the reviewer opens the listing image and each official sibling image, hashes
   the bytes it views (SHA-256) and checks every hash against the pack's prefix, then names the one
   print whose full artwork the listing shows and why each other sibling is excluded. Same-art twins
   (identical pixels) are never resolved.
4. **Proof PR**: one registry entry per review (`review_method`, `actor`, `reviewed_at`,
   `selected_card_print_id`, `considered_print_ids`, `positive_physical_basis`,
   `excluded_sibling_basis`, the capture's `work_id`/`capture_scope`/`baseline_evidence_digest`,
   the snapshot ids and full body SHA-256s). It ships with the collectors (the resolver runs there).
5. **Approval** (`approve-f1-batch`, owner-approved dry run then apply): the now-exact proposals
   (reason `retained_positive_unique_physical_artwork_review`) become mappings through the admin
   guard, and the collectors price them on their own schedule.

## What keeps a review valid

The validator refuses unless the review's capture, snapshots and every full hash match the
retained bytes, the sibling set and release are unchanged, and the listing's identity is unchanged
since the capture was planned (owner 2026-10-29). Identity is the evidence summary without run
provenance and without Yuyu-Tei market state (`YUYU_MARKET_EVIDENCE`: price, stock flag, listing
row text): a price change no longer voids a review, a changed code, rarity, name, image, release,
family or sibling set does. The evidence a capture was planned under is read from the capture's own
summary when it kept one, otherwise from the listing's proposal history, and must hash to the
capture's digest (`source_mapping_proposals.yuyu_identity_unchanged_since`). The same check gates
the capture itself at claim time.

Reviewers come as a method/actor pair: `codex_visual_review_of_unique_full_physical_artwork` with
a `codex:` actor, `claude_visual_review_of_unique_full_physical_artwork` with a `claude:` actor.
