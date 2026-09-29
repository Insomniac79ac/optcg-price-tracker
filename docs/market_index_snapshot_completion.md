# Market Index snapshot completion receipts

## Frozen C1A contract

Authority: `public-ux-market-value-c1a-automation-audit-2026-09-28.md`,
“Deterministic complete-day gate” and “Failure, retry and observability contract”.

A receipt proves that the entire selected physical-print population was archived
as one coherent, nonempty UTC batch. It does not prove complete catalogue price
coverage or successful source collection. Natural identity is `snapshot_date`:
one authoritative receipt per day, protected by a unique constraint.

Required facts are the date, shared `calculated_at`, selected count and sorted-ID
digest, persisted row count and content digest, index/source-semantics versions,
run identity and completion timestamp. Row count alone is insufficient. All rows
must have the same calculation time and version pair. The completion receipt and
new snapshot rows commit in the same transaction, after verification; failure
rolls back both. Normal runtime never updates either archive.

The receipt captures membership at snapshot time. Historical verification must
not compare an old day to today's catalogue. A same-day snapshot retry additionally
checks its selected IDs against that captured membership, then verifies the stored
batch without recalculating or replacing prices. Changed membership, missing rows,
mixed batches or any contradictory receipt fail closed, with no repair.

Empty selection creates no receipt. Snapshot rows without a receipt remain
`receipt_missing` legacy/unqualified evidence; normal snapshot execution refuses
to certify or fill such a day. Receipt existence alone is never sufficient.

## Schema and canonical digests (receipt version 1)

`market_index_snapshot_completions` stores a surrogate `id`, unique
`snapshot_date`, `calculated_at`, `expected_print_count`, `snapshot_row_count`,
`selected_print_ids_digest`, `snapshot_content_digest`, `digest_version`,
`index_version`, `source_semantics_version`, `run_id`, `completed_at` and
`receipt_kind`. Counts are positive and equal; versions positive; digest version
is 1. `receipt_kind` is currently only `atomic`. The run identity is the existing
snapshot lock owner (a generated UUID identity in isolated lock-free tests).
`completed_at` records successful pre-commit verification time, not an asserted
database commit timestamp. Visibility from a fresh transaction proves commit.

Both hashes are lowercase hexadecimal SHA-256 of UTF-8 JSON, with sorted object
keys, no whitespace (`separators=(",", ":")`), unescaped Unicode, and no NaN or
infinity. Dates use `YYYY-MM-DD`; timestamp columns normalize to UTC with exactly
six fractional digits and suffix `Z`. SQLite's naive timestamp columns are read
as UTC. JSON provenance retains its values and array ordering; object key order
does not matter. JSON integral floats normalize to integers, so JSONB's numeric
representation cannot distinguish `1.0` from `1`.

- Selected IDs: `{"format":"market-index-selected-prints-v1","ids":[...]}`,
  strictly positive unique integer IDs, sorted numerically.
- Content: `{"format":"market-index-snapshot-content-v1","rows":[...]}`,
  rows sorted by `card_print_id`. Include every archived semantic field:
  `card_print_id`, `snapshot_date`, `calculated_at`, `index_value_jpy`,
  `calculation_method`, `source_count`, `coverage_status`, `confidence`,
  `source_price_range_low_jpy`, `source_price_range_high_jpy`, `index_version`,
  `source_semantics_version`, `freshest_eligible_source_at`,
  `stalest_eligible_source_at`, `provenance`. Exclude only the surrogate row `id`
  and database insertion metadata `created_at`. Nulls remain JSON null.

These domains and the fixed field list are versioned independently of valuation
methodology. Changing the encoding requires an explicit digest-version contract;
never reinterpret existing hashes. No constituent copies are stored in receipts.

## Verifier and transaction boundary

`verify_market_index_snapshot_completion(db, snapshot_date)` performs a single
SELECT of receipt, rows and producer-lock status. PostgreSQL therefore supplies
one consistent statement snapshot even at READ COMMITTED. It neither flushes,
commits, rolls back nor acquires a lock. It returns structured counts, calculation
and version coherence, digest matches, receipt/run metadata and machine-readable
failure reasons. A still-active snapshot lock prevents downstream acceptance.
The producer's internal pre-commit check permits its own active producer stage;
that internal check is not a downstream completion gate.

Public failure reasons include `receipt_missing`, `duplicate_receipt`,
`row_count_mismatch`, `calculated_at_mismatch`, `version_mismatch`,
`selected_print_ids_mismatch`, `digest_mismatch`, `receipt_invalid` and
`snapshot_in_progress`. Snapshot execution also rejects `empty_selection`,
`selected_population_changed` and a calculation crossing the captured UTC date.
Empty selection remains a reported no-op, with completion unverified.

The snapshot job keeps `market_index_snapshot` locking and its single data
transaction. It verifies pending rows against computed facts, inserts the receipt,
verifies receipt against rows, then commits once. Returned fields are plain values;
there is no post-commit count used as proof. A repeated completed day verifies and
rolls back its read transaction, writing nothing. No historical snapshot backfill
or corrective upsert exists.

Future downstream orchestration must finish/close the producer session, verify
completion in a fresh transaction, and revalidate the evidence in the consistent
read view used for derivation. It must qualify every pending consumed date and
verify the existing derived prefix; receipts do not replace those C1B1 checks.
No orchestrator or scheduler is added here; the Railway command is unchanged.

## Legacy September 27

**SEP27_CAN_BE_GUARDED_LEGACY_CERTIFIED** is the C1A design conclusion: that audit
independently established terminal success, exact population and coherent rows.
It authorizes a separate, explicitly reviewed operator certification path after
revalidating the evidence at rollout. This tranche implements no retrospective
certification command and creates no historical receipts. In particular, it must
never label retrospective evidence `atomic`; a future path needs its own explicit
provenance contract. September 27 remains receipt-less until that work is approved.

## Backup and rollout

Receipts accompany `market_index_snapshots` under `include_prices` in application
backup version 15. Versions 12–14 remain readable and legitimately omit receipts;
restore never manufactures them. New runtimes validate restored receipts against
the restored archive before commit. Merge restore refuses conflicting receipt
facts rather than correcting them. Existing backup files are not changed.

Apply the additive migration before deploying receipt-writing code. Deployment
and migration application are separate operator actions, not part of C1B0. The
migration does not backfill or modify any existing table. CPI, Market Value,
collectors and public frontend behavior are unchanged by this foundation.
