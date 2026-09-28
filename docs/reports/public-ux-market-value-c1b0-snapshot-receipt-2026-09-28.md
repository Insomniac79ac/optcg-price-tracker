# Market Value C1B0 — snapshot completion receipt review

## Scope and baseline

Base and initial branch SHA: `b02b5e3df05b5dc6b9ed3d13bab3f7936fe956a7`.
Branch: `feature/market-value-c1b0-snapshot-receipt`. Fetched `origin/staging`
matched the requested base; tracked tree was clean before implementation.
Unrelated untracked workspace evidence was preserved and excluded from commits.

The C1A audit was read first. Its completion requirements are frozen in the
[receipt contract](../market_index_snapshot_completion.md), including exact
canonical digest encoding. This tranche adds the receipt foundation only: no
orchestrator, source requests, methodology changes, frontend changes, live data
writes, staging migration, Railway configuration or production access.

## Durable contract

One authoritative `market_index_snapshot_completions` receipt per UTC
`snapshot_date`, enforced by a unique constraint. Facts: shared calculation time,
expected and persisted positive counts, SHA-256 of selected IDs and complete
semantic snapshot contents, digest version, index/source-semantics versions,
run identity, completion time and `atomic` provenance kind.

The snapshot producer verifies computed facts against its pending database rows,
inserts the receipt, verifies receipt against rows and commits once. Separate
readers see neither object before commit and both afterward. No post-commit count
authorizes success. Existing pricing calculations and job locking are reused.

The read-only verifier reads receipt, archive and producer status in one SQL
statement. Counts alone do not suffice: exact population/content hashes, shared
UTC calculation time and version pair must match; an active producer blocks
downstream acceptance. Missing, duplicate or contradictory receipts fail closed.
Future derivation must use a fresh consistent read view, qualify every pending
consumed date and separately verify its persisted prefix.

Same-day retry verifies immutable evidence and unchanged selected membership,
then returns a no-op. Empty selection produces no receipt. Receipt-less existing
rows are never filled or automatically certified by the normal snapshot path.

Migration: `e6a8b0c3d5f7`, parent `d5f7a9c2e4b6`. It only creates the new table and
its constraints/index; downgrade only removes that table. No historical backfill.

**SEP27_CAN_BE_GUARDED_LEGACY_CERTIFIED**: C1A permits separately audited legacy
certification after revalidation. No retrospective command or historical receipt
is implemented here; September 27 remains legacy until that separately reviewed
path exists. Retrospective evidence must never be labeled `atomic`.

## Backup policy

Application backup v15 includes receipts beside snapshots under `include_prices`.
Versions 12–14 remain readable without fabricated receipts. Restore checks receipt
integrity before commit; merge rejects conflicting receipt facts rather than
updating them. PostgreSQL export/replace round-trip retains exact verifiable
evidence. Existing archives are not mutated.

## Validation

| Suite | Result |
| --- | ---: |
| Receipt canonicalization, verifier and snapshot unit tests | 19 passed |
| PostgreSQL receipt/migration/atomicity/backup tests | 23 passed |
| Receipt backup compatibility/integrity tests | 7 passed |
| Snapshot, Market Index, CPI, Market Value, API, backup/migration regressions | 727 passed |
| Mapping/backup foundation regressions | 18 passed |
| Yuyutei mock/transaction regressions | 480 passed, 42 subtests passed |
| SNKRDUNK mock regressions | 364 passed, 32 skipped, 48 subtests passed |

Totals: **49 focused tests; 1,589 regression tests passed**, excluding subtests.
The collector suites invoked tests with mocked source responses, not collectors.
Eight existing Yuyutei transaction tests require PostgreSQL 16; the initial run
against PostgreSQL 18 correctly rejected that environment. All eight passed
unchanged on disposable PostgreSQL 16. No collector code/assertions were changed.

PostgreSQL 18 proofs include upgrade → downgrade → upgrade; unchanged existing
columns, constraints, indexes and row counts; unique daily identity; one final
commit; separate-connection visibility; failure during calculation/insertion,
after row insertion, on receipt constraint insertion and receipt verification;
same-day no-op; count/time/content contradictions; missing and duplicate receipts;
active producer refusal; and read-only verification enforced by PostgreSQL.

`compileall`, `pip check`, focused formatting check and `git diff --check` passed.
The initial sandbox-only API TestClient run stalled; its process was terminated
and the complete suites passed outside that sandbox. Disposable PostgreSQL
containers used temporary memory-backed data and were stopped/removed after tests.

Disk before/after local validation: **13 GB available, 59% used (~41% free)**.
No application Docker stack was recreated. Stop point: PR review, before migration
application or C1B1 orchestration.
