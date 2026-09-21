# Proposal decision schema contract

Source Mapping Coverage 1B1C2B1 adds the database foundation for auditable,
terminal proposal decisions. It does not add a decision writer, mutation route,
or user-interface action.

## Decision record

`source_mapping_proposal_groups` retains the decision as a snapshot:

- `reviewed_at` is the UTC decision time.
- `reviewed_by` is the authenticated reviewer identity captured by the server.
- `review_notes` is optional for approval and required, after trimming, for
  rejection.
- `selected_alternative_id` identifies the approved alternative.
- `decision_basis_updated_at` retains the pre-decision group `updated_at` value
  presented to the reviewer. It is not the group's post-decision timestamp.

All five columns are nullable and have no server default. Existing pending rows
therefore remain valid with NULL decision fields and require no backfill.

The lifecycle check permits only three complete shapes: an undecided pending
group with no decision metadata or mapping; an approved group with reviewer,
time, concurrency basis, selected alternative, and resulting mapping; or a
rejected group with reviewer, time, concurrency basis, nonblank reason, and no
selected alternative or resulting mapping.

The selected alternative is protected by a composite foreign key from
`(selected_alternative_id, id)` to alternative `(id, proposal_group_id)`. An
alternative from another group cannot be selected. A partial unique index also
allows at most one alternative whose `review_disposition` is `approved` in a
group. The future decision service must update the selected alternative and
group atomically; this tranche intentionally adds no cross-row trigger.

Phase one treats decisions as terminal. A future reopen or reversal workflow
should add an append-only decision-event model rather than overwrite the
identity, time, note, or concurrency basis captured here.

## Reviewer identity boundary

`reviewed_by` is server-derived. It must never be accepted from an ordinary
request-body field or an unsigned `X-Reviewer` header.

The current FastAPI `require_admin_token` dependency proves possession of a
shared admin token but does not identify an individual reviewer. The Next.js
server proxy already has a validated Auth.js admin ID/email. A future mutation
tranche must have that server mint a short-lived, signed, backend-only actor
assertion; FastAPI must validate the assertion before copying its canonical
actor identifier into `reviewed_by`. The assertion must never reach browser
JavaScript, and the temporary admin must not be JIT-created as a normal
collector `User` row.
