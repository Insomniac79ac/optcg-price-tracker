# Receipt-gated forward Market Value publication

Normal publication is an explicit operator action. It does not schedule jobs,
collect sources, generate snapshots, or create completion receipts. Use the same
reviewed staging connection/identity checks and recovery-point procedure as other
staging writes in [operations](operations.md#staging-operations). No migration is
added; the C1B0 completion schema must already exist.

From `services/api`, with the intended database configured:

```sh
# Read-only plan; PostgreSQL enforces REPEATABLE READ READ ONLY.
python -m app.market_value_publisher --dry-run

# Publish all currently eligible NEW receipt-backed dates, in date order.
python -m app.market_value_publisher --write

# Plan/publish exactly one date; no implied earlier dates or backfill.
python -m app.market_value_publisher --dry-run --date 2026-09-29
python -m app.market_value_publisher --write --date 2026-09-29
```

There is no `--through` option on the forward publisher. No write mode is implicit.
`--date` must have a valid receipt. A date behind the existing publication head
is rejected unless already published, in which case its receipt and persisted
history must verify before a no-op. Selecting one later date deliberately leaves
other unpublished earlier dates behind; subsequent runs never backfill them.

## Selection, verification and immutability

1. Determine the latest persisted Market Value date across the existing archive.
   Consider only completion-receipt dates later than that head (or the requested
   single date). With an empty archive, only receipt-backed dates can seed it.
2. Verify every referenced receipt using C1B0's
   `verify_market_index_snapshot_completion`, including any receipts attached to
   already published history. Missing/contradictory requested receipts, invalid
   hashes/populations/times/versions, and an active producer fail closed. An invalid
   later candidate aborts the whole invocation; no earlier candidate is committed.
3. Load an explicit SQL date allowlist: **already published dates plus verified
   new dates**. Unpublished receipt-less snapshots do not enter the derivation.
   Full receipt populations are verified before applying the unchanged Market
   Value active/verified/JP/release-FK eligibility rules.
4. Recompute the existing persisted history and require an exact match for every
   scope and deterministic field. Legacy already-published dates may lack receipts;
   they are accepted only as verified existing history, never as new candidates.
   Partial days, obsolete scopes, changed catalogue membership or conflicting
   values abort. There is no automatic repair, overwrite, or membership migration.
5. Derive and insert only the new dates with the existing formulas, thresholds,
   release rules, methodology version and natural keys. Verify the complete result
   before a single commit. An identical retry verifies and inserts zero rows.

For the staging example, persisted history ends September 26; September 27–28
have snapshots but no receipts; September 29 has a valid receipt. Only September
29 is appended. The existing engine sees a three-day gap from September 26. It
preserves the literal tracked JPY value but starts a new movement segment; the
public read model reports insufficient continuity for windows spanning that gap.
Neither zero-return days nor September 27–28 points are invented. This is the
existing methodology's gap behavior, not a new formula or API contract.

## Transaction and producer races

Writes use the existing `market_value_writer` job lock, shared with recovery.
The caller must supply a fresh session transaction. Receipt verification, archive
and catalogue reads, persisted-prefix comparison, derivation, insertion and final
verification occur in one PostgreSQL REPEATABLE READ transaction.

Before inspecting receipts, a write takes a shared `NOWAIT` row lock on the
existing `market_index_snapshot` job-lock row. An active/missing producer row or a
concurrent transition refuses publication. A normal producer's acquire UPDATE
cannot start until this transaction ends. The publisher does not acquire or
force-release the snapshot job lock. Dry runs take no row/job locks and assess
one consistent read-only view; a successful dry run is not authorization evidence
for a later write, which performs the full gate again.

## Historical recovery remains explicit

The original replay adapter still loads every archived date by default; reports
and explicit rebuild/recovery retain their existing behavior. Recovery can
consume receipt-less dates and must never be used as the forward publication path.
CLI recovery writes now require an explicit acknowledgement:

```sh
python -m app.market_value_writer --dry-run --through 2026-09-26
python -m app.market_value_writer --verify --through 2026-09-26
python -m app.market_value_writer --write --replay --through 2026-09-26
```

`--write --through ...` without `--replay` is rejected before opening a database
session. The programmatic `run_writer` recovery API retains its semantics.
Recovery replay is not a way to verify a forward series with deliberately skipped
archive days: those extra days alter replay chronology, so its exact-value gate
can correctly reject that series. Use the forward publisher's read-only plan to
verify the actual publication timeline.

## Call-site audit and rollout boundary

Tracked scheduler/orchestrator inspection found **no Market Value invocation** in
`services/worker/worker/celery_app.py`, `deploy/`, `.github/workflows/`, `scripts/`,
or `Makefile`. The existing documented Railway snapshot cron chains
`app.snapshot_market_index` and `app.card_pirate_index_writer`; it does not invoke
Market Value. No scheduler configuration is changed here.

The old Market Value writer's callers are its own CLI `main()` and explicit
writer tests; replay reporting calls the adapter directly. Historical operations
reports retain their original `--through` seed/audit commands as evidence. Future
manual forward runbooks or orchestration must call `app.market_value_publisher`,
not reuse those recovery commands. There is no in-repository automated caller to
switch in this tranche; external operator commands are not exhaustively knowable
from a repository audit.

This change is code and tests only. Deploying it, running a staging publication,
or introducing unattended orchestration are separate operations.
