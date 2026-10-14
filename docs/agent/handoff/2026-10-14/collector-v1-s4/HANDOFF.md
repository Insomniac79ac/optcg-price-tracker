# Collector v1 S4 handoff: daily collection value history on staging (2026-10-14)

Plan: `docs/agent/plans/collector-v1/PLAN.md` §B3, §C3, §C4, §H row S4, owner
decisions Q4 and Q5 (on `plan/collector-v1`, APPROVED). Target: staging only.
Production was not accessed (`production_accessed: false`). Level: AMBER
(`subsystem_activation`: a new stage in the daily `market-index-snapshot` job).
No migration. No collector release. `COLLECTOR_ACCOUNTS_ENABLED` stays unset.

## Plain summary

The daily 20:00 UTC price job now has one more step at the very end. After Market
Value and the Card Pirate Index are done, it records each collector's collection
value for the day. Staging has no collectors yet, so tonight it should record
nothing. The `/me` collection value endpoint can now show 7D, 30D and ALL change
and a clearly labelled day-one preview, but it stays switched off (404) until S5.
Market Value, the Index, prices and identity are unchanged. No collector was
redeployed.

## Delivery (PR #121)

| Item | Value |
|---|---|
| PR | #121, draft 2026-10-14T09:19Z, rebased onto `4c53dfa` (PR #120) after that delivery was released, marked ready 10:10:36Z, native auto-merge by the delivery job |
| Head | `1ac5a287153d04db745cd385d3a112c9b96714f1` (code `f53f13d`, manifest `1ac5a28`) |
| Merge commit | `20f167e6383a6329513882d64c7f427911f4b51b`, merged 2026-10-14T10:27:31Z |
| CI runs | `38541470609` (draft, pre-rebase head: success), `38547668694` (rebased head: success), `38547720657` (ready: success, incl. `engineering-gate`, `staging-automerge`, delivery) |
| Classification | AMBER, eligible (`scripts/staging_policy.py`, 0 errors). Scope `full`, `collector_services` empty, no migration |
| Size | 11 files (4 code, 3 tests, 3 docs, manifest) |

### Preflight gates (all checked immediately before marking ready)

| Gate | Evidence |
|---|---|
| Backup < 24 h | `4654fa96-c582-4dfb-a3fc-74c0759263be` (Daily Schedule), created 2026-10-14T09:22:01Z, **0.81 h** old at 10:10:26Z (`evidence/backups-preflight-3.json`). At 08:43Z the newest was 23.35 h old (`-1.json`); the merge was held until the 09:22 daily backup |
| Merge window | Ready 10:10Z, merged 10:27Z: inside 06:00-19:00Z, clear of 19:30-20:30Z |
| Serialization | Sibling session's PR #120 (official images) merged 09:56:52Z, delivery run `38544725025` green 10:09:50Z; it confirmed "released" before #121 left draft. No capacity session running (only one peer session on the machine) |
| Disk | 2.4 GB free at start. Removed `node_modules` in the merged `cp-cv1-s2` and `cp-fonts` worktrees and the npm cache (3.9 GB); the owner freed the rest (7.5 GB). Removing stopped test Postgres containers was refused by the permission classifier and not attempted another way |

### Receipts (downloaded into `evidence/pr121-delivery/`)

| Artifact | Id | Expires |
|---|---|---|
| `staging-delivery-20f167e6383a6329513882d64c7f427911f4b51b` | 11887116050 | 2027-01-12T10:10:39Z |
| `staging-credential-probe-1ac5a287153d04db745cd385d3a112c9b96714f1` | 11885451258 | 2027-01-12T10:10:39Z |

- `latest-staging-delivery.json`: verified **2026-10-14T10:40:58Z**. Scope `full`.
  API expectation `build` at `20f167e` (watched changes: the four API files and
  tests). Migration revision **`3b7d9c1a5e20`** (unchanged). Frontend
  `dpl_9wEFK6X3stUZjMfsK9Sas6vNBeqZ` READY at `20f167e`. Routes `/`,
  `/prints/5661`, `/analytics` rendered. Sale invariant: 227 public sale
  histories, 0 sale index inputs, 0 gap receipts. 0 GET timeout retries.
- Credential probe: VERIFIED, `production_accessed: false`.
- Railway records since 10:10Z (`evidence/deploy-records-after-pr121.json`,
  10:41:34Z): **API `optcg-price-tracker` SUCCESS and `market-index-snapshot`
  SUCCESS at `20f167e`** (10:27:34Z); `worker` and `beat` SKIPPED. **0 deployments
  on all 11 collector services.** No rollout requested, so no
  `latest-collector-rollout.json`.

### After deploy

- `/me` probe (`evidence/me-probe-after-deploy.json`, 10:41:56Z): all 9 GETs,
  including `/me/collection/value?window=all`, answer **404** (flag off).
- OpenAPI (`evidence/openapi-collection-value-after-deploy.txt`): `window` enum
  `7d|30d|all`; `CollectionValueOut` has `history` and `preview`. The code is live.
- `/health`: `git_commit: unknown` (see For S5).
- Staging state (`evidence/staging-state-after-deploy.json`, read-only, 10:42:20Z):
  alembic `3b7d9c1a5e20`; `users` 0, `collection_entry_events` 0,
  `collection_value_points` 0 rows.

## Stage design

`services/api/app/accounts/value_history.py`, called from
`app/market_index_daily_pipeline.py::_run_downstream` **after** CPI.

- **Order and isolation.** Snapshot → receipt gate → Market Value → CPI →
  `collection_value`. The stage opens its own session, its own REPEATABLE READ
  transaction and its own job lock `collection_value_history` (default 30 min TTL;
  `job_locks.py` not edited because collectors may import it). It runs inside the
  coordinator's existing shared `NOWAIT` guard on the producer lock (proved on
  Postgres). Any exception becomes `collection_value: failed` (exit 1); a held lock
  becomes `locked` (exit 2). Market Value and CPI have already committed and their
  report entries are unchanged. A failed gate leaves the stage `skipped`.
- **What it writes.** For the receipted day only, one row per user holding at
  least one exact card. Holdings come from `collection_entry_events` as of that
  day's receipt `completed_at` (the moment prices were final), so a rerun produces
  the same rows; later changes belong to the next day. A missed day stays
  missing; nothing is backfilled.
- **Values.** `valuation.load_day_values` (the S3 adapter, the same usable value as
  Market Value: positive archived `index_value_jpy` on receipted days, Yuyu-Tei sale
  excluded, no forward fill). `value_jpy` is null when nothing is priced, never 0.
- **Daily step.** Only when the previous calendar day has a verified receipt
  (otherwise `prior_day_missing`, a break). `valuation.endpoint_step`: units held
  on both days (`min`), Market Value comparability (index and semantics versions,
  same non-empty contributor set), `P > 0`, comparable value ≥ 80% of priced value
  at both ends; **no minimum card count** (Q4). `P`/`Q` stored only when `P > 0`.
  `segment_number` increments after any break.
- **Idempotency.** Insert with `ON CONFLICT DO NOTHING`, then every derived column
  must equal the draft; otherwise the stage fails and rolls back (Market Value
  writer pattern).
- **Reads.** `GET /me/collection/value?window=7d|30d|all` adds `history`
  (`kind: "recorded"`: chained stored `Q/P`, integer products, one division,
  50-digit Decimal; any missing point → `history_missing` with the dates; any
  unpublishable step → its reason and `failed_step_date`; never 0%) and `preview`
  (`kind: "preview"`, label "Preview: how the cards you hold now moved over the
  last 30 days. This is not your collection's recorded history."; derived on read
  from current cards over the last 30 receipted days; days without a receipt are
  absent, so the line breaks). Movers for `all` start at the first recorded day.
- **Cost.** Per run: two receipt verifications (today, yesterday), one ledger scan
  (all events before the cutoff), two archive reads for held prints. The preview
  verifies up to 31 receipts on the first request per API process, then caches.
  Size per row as planned (~200 B, §B3); 0 rows today.

Docs: `docs/collector_accounts.md` (recorded history section),
`docs/market_value_daily_pipeline.md` and `docs/operations.md` (dated notes:
the coordinator **is** the live staging start command; both docs still said
"prepared, inactive"; checked read-only via `railway status`:
`python -m app.market_index_daily_pipeline`, cron `0 20 * * *`).

## Tests

New: `tests/test_collection_value_history.py` (SQLite, 20),
`tests/test_collection_value_history_postgres.py` (migrated Postgres 18, 4),
`tests/test_collection_value_history_import_graph.py` (2).

| Requirement | Test |
|---|---|
| Step/window math vs an oracle | `test_steps_and_windows_match_the_oracle`: 12 days, two users, adds, removals, unpriced days, a cutoff edge; every point and the 7D/ALL change vs an independent `Fraction` restatement |
| Quantity changes never gain or loss | `test_quantity_changes_never_count_as_gain_or_loss` (flat prices, size changes daily → every step P = Q, 7D = `0.00`) |
| Missing day is a break, never 0% | `test_a_missing_day_is_a_break_never_zero`, `test_a_day_the_stage_did_not_run_is_also_a_break` |
| 80% guard, no minimum counts | `test_eighty_percent_guard_with_no_minimum_card_count` (one card publishable; guard failure; exactly 80% passes) |
| Idempotent rerun | `test_rerun_is_idempotent_and_ignores_later_changes`, `test_stage_rerun_through_the_pipeline_is_a_no_op`, `test_a_contradicting_stored_point_fails_closed` |
| MV and CPI outputs unchanged | `test_market_value_and_index_outputs_are_unchanged_by_the_stage[real_with_collectors, real_without_collectors, failing, locked]`: every MV and CPI column (except run timestamps) and stage result equal to the stage-stubbed (pre-S4) run; Postgres `test_stage_presence_or_failure_leaves_index_outputs_identical` |
| Unpriced never 0 | `test_unpriced_cards_are_never_zero`, `test_value_constraints_reject_a_zero_value` (Postgres CHECK) |
| Yuyu sale excluded | `test_yuyu_sale_prices_are_excluded_from_recorded_points` (real Market Index snapshot path) |
| Report / gate | `test_report_lists_the_stage_and_gate_failure_skips_it` (exact `collection_value` JSON for 0 users) |
| Producer guard, isolation | `test_stage_writes_points_under_the_producer_guard`, `test_stage_transaction_is_repeatable_read` (Postgres) |
| API | `test_value_endpoint_reads_recorded_history_and_a_labelled_preview`, `test_preview_breaks_on_a_missing_day_and_history_is_empty_on_day_one`, `test_value_endpoint_with_no_cards_or_prices` |
| Rollback | `test_rollback_by_methodology_version_removes_only_s4_rows` |
| Import graph (0 collector inputs) | `test_no_collector_reaches_the_s4_files[snkrdunk, yuyutei]`; S3's `test_no_always_collector_input_changed_against_staging` still passes |

### Full API suite (Postgres 18.6 on localhost:5545)

| Run | Result |
|---|---|
| `origin/staging` `99806ef` (`evidence/full-api-suite-staging-99806ef-pg18.txt`) | 5154 passed, 41 skipped, 0 failed |
| S4 `d3f5159` (`evidence/full-api-suite-d3f5159-pg18.txt`) | **5180 passed, 41 skipped, 0 failed** |
| S4 rebased `f53f13d`, targeted (S4, accounts, pipeline, MV publisher, CPI writer; SQLite + Postgres) | 268 passed (`evidence/targeted-suite-f53f13d.txt`) |

`evidence/skip-comparison-d3f5159-vs-99806ef.json`: **identical skip set** by id
and reason (41 = 41); no baseline test missing; the +26 are exactly the new tests.

**Environment difference from S1-S3:** port 5544 was held by another session's
container (`lockpg`, Postgres 16), so this session's Postgres 18 ran on 5545 with
`TEST_POSTGRES_URL/HOST/PORT/USER/PASSWORD` set. Both runs excluded
`tests/test_raw_dictionary_storage_postgres.py`, which hardcodes
`localhost:5544` by design and would have created a schema in the other
session's database. That file is why both totals are 27 lower than S2's 5181
baseline. Runner: `tools/run_suite.sh`.

Import graph (`evidence/import-graph-check-d3f5159.json`, installed component
`a504e47`): snkrdunk and yuyutei **0 changed runtime inputs**, 0 PR files in
either import set, no `app/accounts` module reached, nothing under
`app/models/**`, `settings.py` or requirements touched. All 11 collectors were
on `a504e47` (PR #119 `CURRENT_STATE.yaml`).

## Tonight's 20:00 UTC run (verification pending at handoff time)

Do **not** trigger the job. Baseline (`evidence/pipeline-reports-before-s4.txt`,
Railway logs of the six previous natural runs, 2026-10-08..13, 20:01-20:05Z):
every run `snapshot` succeeded 2626, `receipt` verified, `market_value`
succeeded **60**, `card_pirate_index` succeeded **1**, `exit_code=0`.

Expected on 2026-10-14 (first run on deployment `20f167e`):

1. The report line contains `collection_value={"dates":["2026-10-14"],"inserted":0,"reason":null,"status":"no_op"}`
   (0 users, 0 ledger events).
2. `market_value` succeeded 60 and `card_pirate_index` succeeded 1 (or whatever
   the snapshot/receipt pattern implies, same as before), `exit_code=0`.
3. Read-only: `collection_value_points` still 0 rows; `job_locks` has a
   `collection_value_history` row, `released`.

How to check (read-only; replace the deployment id if a newer one is active):

```sh
railway logs <market-index-snapshot deployment id> -p c613898d-bf03-43a6-8813-761f72e1c00a \
  -e 05d1eac2-510d-4bd3-999e-fea9ead766b7 -s 8d2ee55a-992f-42e0-99a1-99e17df44dd2 \
  --deployment --lines 300 | grep exit_code=
python3 tools/staging_readonly.py state      # collection_value_points rows
python3 tools/db.py "SELECT lock_name, status, acquired_at FROM job_locks WHERE lock_name='collection_value_history'"
```

The deployment active at 20:00Z is the `SUCCESS` one at `20f167e` (created
10:27:34Z) unless something else deploys `market-index-snapshot` before then.
**If the stage failed**, Market Value and CPI are still committed (independent);
roll back per below and record the reason from the report.

This session keeps a read-only watcher on that log and will report the result to
the owner; if this handoff is read before a follow-up record exists, the next
session must perform the check above and record it.

## Rollback

Revert PR #121 (API and `market-index-snapshot` redeploy through their normal
triggers). Then delete the private, non-published rows:
`DELETE FROM collection_value_points WHERE methodology_version = 1` (0 rows on
staging today). No migration to undo.

## Receipts carried here

**PR #119 (S2 handoff)**, committed under
`docs/agent/handoff/2026-10-13/collector-v1-s2/evidence/pr119-delivery/` with
`deploy-records-after-pr119.json`:

| Item | Value |
|---|---|
| Merge commit | `99806ef9d114ac310a4b6b9bc241e44966cf139e`, merged 2026-10-13T23:22:56Z |
| CI run | `38482095075` |
| Artifacts | `staging-delivery-99806ef…` 11859305306, `staging-credential-probe-658ecd5…` 11858685500, both expire 2027-01-11T23:05:47Z |
| Receipt | verified 2026-10-13T23:35:12Z, scope `skip` (docs only), API expectation `skip` at `eaf9de7`, migration `3b7d9c1a5e20`, 0 timeout retries, `production_accessed: false` |
| Collector deployments | **0** of 11 since 23:05Z (Railway records at 10:42:52Z); every non-collector service SKIPPED at `99806ef` |

**PR #120** (official images, the sibling session's delivery, merged
`4c53dfa` at 09:56:52Z, run `38544725025` green) is recorded by that session.

## Pending

1. Tonight's 20:00Z run check (above).
2. This handoff PR's own receipt (docs only; expected scope `skip`, 0 collector
   deployments, revision stays `3b7d9c1a5e20`): download it first in the next
   collector-v1 session.
3. From S2: owner confirmation of the Sentry test events and a Vercel page view
   was not recorded in this session (no Sentry or Vercel Analytics access here).

## For S5

1. **API release SHA missing in Sentry.** `RAILWAY_GIT_COMMIT_SHA` and
   `GIT_COMMIT` are unset on the API service; `/health` shows `git_commit:
   "unknown"` (re-observed 2026-10-14T10:41:56Z). Pass the commit as a build arg or
   set a release source so Sentry events and `/health` carry the SHA.
2. **Rotate the Vercel protection-bypass secret** and update the GitHub secret
   that CI uses for it.
3. **Rotate `ADMIN_TOKEN` and `AUTH_SECRET`.**
4. **Delete stale Vercel branch preview variables.**
5. S5 enables `COLLECTOR_ACCOUNTS_ENABLED`; from the first test user's first
   ledger event, the 20:00 stage starts writing points. The S7 UI must render
   `preview` visually separate from `history` (Q5).

## Notes and follow-ups (proposed, not done)

- **Stale docs corrected:** `market_value_daily_pipeline.md` and `operations.md`
  described the coordinator as inactive; it is the live start command.
- **Port 5544 contention:** concurrent sessions on one Codespace can collide on
  the hardcoded test port. S3's proposed `tests/postgres_env.py` helper (derive
  every Postgres test connection from `TEST_POSTGRES_URL`) would also remove the
  need to exclude `test_raw_dictionary_storage_postgres.py`.
- Worktrees: `/workspaces/cp-cv1-s4` (code), `/workspaces/cp-cv1-s4-handoff`
  (this record). The baseline worktree `/workspaces/cp-cv1-s4-base` and the test
  container `cv1-s4-pg18` are removed at the end of the session.
