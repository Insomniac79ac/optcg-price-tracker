# Collector v1 S3 handoff: account tables and dark /me API on staging (2026-10-13)

Plan: `docs/agent/plans/collector-v1/PLAN.md` §B1, §C and §H row S3 (on `plan/collector-v1`).
Target: staging only. Production was not accessed (`production_accessed: false`).
Level: AMBER (one additive migration). No collector release.

## Plain summary

Staging now has the five empty tables that will hold collectors' collections,
watchlists, preferences and daily values. The API has the `/me` endpoints for them,
but they are switched off: every `/me` route answers 404 until S5 sets
`COLLECTOR_ACCOUNTS_ENABLED`. No existing table, row, price, Market Value or Card
Pirate Index changed, and no collector was redeployed.

## Delivery

| Item | Value |
|---|---|
| PR | #112, opened as draft 2026-10-13T09:54:21Z, marked ready 09:56:08Z, native auto-merge enabled 09:56:46Z by the delivery job |
| Head | `10e2fbc1b1ef75f51c2fc64b014ca1e555eff68d` (rebased on `b9d1c21`, the S1 handoff merge) |
| Merge commit | `5d86629fc8679849e9bcb79121d0407e813f2166`, merged 2026-10-13T10:14:19Z |
| CI runs | `38379656526` (draft push: 17 success, 2 skipped), `38379865021` (ready: all 19 jobs success, including `engineering-gate`, `staging-automerge`) |
| Classification | AMBER, eligible (`scripts/staging_policy.py`, 0 errors). Scope `full`, no `collector_services`, no RAW migration requested |
| Size | 17 files, +3,748 / −6 (plus the manifest) |

Commits: `11dceb6` tables and dark API, `7920e3d` test-only admin assertion fix,
`793d203` legacy `file_jobs` deletion, `10e2fbc` manifest.

### Receipts (downloaded into `evidence/pr112-delivery/`)

| Artifact | Id | Expires |
|---|---|---|
| `staging-delivery-5d86629fc8679849e9bcb79121d0407e813f2166` | 11803728600 | 2027-01-11T09:56:11Z |
| `staging-credential-probe-10e2fbc1b1ef75f51c2fc64b014ca1e555eff68d` | 11803231962 | 2027-01-11T09:56:11Z |

- `latest-staging-delivery.json`: verified 2026-10-13T10:25:44Z. API expectation
  `build` at `5d86629` (watched API changes). **Migration revision `3b7d9c1a5e20`.**
  Frontend `dpl_GN3GzNKPmBTwSA5J7SSLDw2NMX2Z` READY at `5d86629`. Routes `/`,
  `/prints/5661`, `/analytics` rendered. Sale invariant: 227 public sale histories,
  0 sale index inputs, 0 gap receipts. 0 GET timeout retries.
- Credential probe: VERIFIED, `production_accessed: false`.
- Railway records since 09:56Z (`evidence/deploy-records-after-pr112.json`):
  API `optcg-price-tracker` and `market-index-snapshot` one SUCCESS each at
  `5d86629` (10:14:22Z); `worker` and `beat` SKIPPED (no watched change).
  **0 deployments on all 11 collector services** and on both `tmp-*` services.
  No rollout requested, so no `latest-collector-rollout.json`.

## Migration

| Item | Value |
|---|---|
| Revision | `3b7d9c1a5e20` (parent `6c2242f6f439`), one transaction |
| Applied | 2026-10-13T09:54:55Z, before the PR left draft, with `tools/apply_migration.py upgrade` (`alembic upgrade` via the staging TCP proxy, `lock_timeout=10s`, `statement_timeout=120s`; credentials read at run time, never written) |
| Result | `evidence/migration-upgrade.json`: alembic exit 0, `6c2242f6f439` → `3b7d9c1a5e20` |
| DDL | `evidence/migration-3b7d9c1a5e20-offline.sql` (generated offline first): 5 `CREATE TABLE`, their indexes, the `alembic_version` update. Nothing else |
| Backup gate | Newest staging Postgres volume backup `e1a2c03c-0660-47d3-a34c-dd1ec2f53839` (Daily Schedule), created 2026-10-13T09:22:01Z, **0.16 h old** at the check (`evidence/backups-preflight-3.json`). Schedule `22 9 * * *`, 6-day retention |
| Rollback | Revert the PR, then `alembic downgrade 6c2242f6f439` (`tools/apply_migration.py downgrade`). The downgrade refuses if any of the five tables has a row |

### Tables and sizes (for the capacity mission)

After deploy (`evidence/staging-state-after-deploy.json`, 10:26:54Z): alembic
`3b7d9c1a5e20`, every table exists and is empty.

| Table | Rows | Bytes (`pg_total_relation_size`) | Columns | Indexes |
|---|---|---|---|---|
| `collection_entries` | 0 | 49,152 | 12 | pkey, `ix_…_user_id`, `ix_…_card_print_id`, `uq_…_user_print`, `uq_…_legacy_item` |
| `collection_entry_events` | 0 | 16,384 | 6 | pkey, `ix_…_user_print_time` |
| `watchlist_entries` | 0 | 49,152 | 10 | pkey, `ix_…_user_id`, `ix_…_card_print_id`, `uq_…_user_print`, `uq_…_legacy_item` |
| `user_preferences` | 0 | 8,192 | 4 | pkey |
| `collection_value_points` | 0 | 8,192 | 16 | `pk_collection_value_points` |
| **Total** | 0 | **131,072 (128 KB)** | | |

Database size 2,842,269,375 → 2,842,547,903 bytes across the upgrade (+272 KB:
the 128 KB of new tables plus whatever collectors wrote in the same seconds).

Legacy dry run after the migration (`evidence/legacy-dry-run-postmigration.json`,
read-only transaction): `collection_items` 0, `wishlist_items` 0 → **0/0**, nothing
to copy. Legacy `cards`: 25 (10 exact, 6 reach several prints, 9 reach none), as the
plan recorded. Legacy `users` 0.

## Endpoints and flag state

Routes (all bearer JWT, `Cache-Control: private, no-store`): `GET/POST
/me/collection`, `PATCH/DELETE /me/collection/{id}`, `GET /me/collection/value`,
`GET/POST /me/watchlist`, `PATCH/DELETE /me/watchlist/{id}`, `GET/PUT
/me/preferences`, `GET /me/export`, `GET /me/export/{collection,watchlist}.csv`,
`DELETE /me?confirm=delete my account`. Details: `docs/collector_accounts.md`.

**Flag: `COLLECTOR_ACCOUNTS_ENABLED` is not set on the staging API service**
(checked by key name only before the PR and again after deploy at 10:28:17Z, `evidence/flag-check-after-deploy.json`; no values read or printed). It is read by
`app/accounts/config.py`, not `app/settings.py`, so no collector imports it.

- The deployed OpenAPI lists all 9 `/me` paths (`evidence/openapi-me-after-deploy.json`),
  so the code is live.
- Unauthenticated GETs to all 8 `/me` GET routes answer **404 `{"detail":"Not Found"}`**
  after deploy (`evidence/me-probe-after-deploy.json`, 10:26:35Z). The 404 comes
  from the flag dependency, before authentication. Before deploy they were also 404
  (`evidence/me-probe-before-deploy.json`), because the routes did not exist yet.
- No mutating request was sent.

S5 turns the flag on (RED gate: auth/security policy, owner Q2 and D2 steps first).

## The SET NULL correction

PLAN §D ("Delete my account") says `ON DELETE CASCADE` removes `saved_views` and
`search_history` with the user. It does not: those foreign keys are **SET NULL**,
so deleting the `users` row would leave the rows behind with a null owner. And
`file_jobs.user_id` has **no foreign key at all**, so a user's CSV export jobs and
their stored files would survive too.

S3 handles both in `DELETE /me` (`app/accounts/service.py`): the user's
`saved_views`, `search_history` and `file_jobs` rows are deleted explicitly in
the same transaction as the user, and the jobs' stored files are removed after
the commit, the way `cleanup_old_file_jobs` does. Admin backup jobs carry no user
and are untouched (`793d203`).

Proof: `test_after_delete_me_no_table_carries_the_users_id`
(`tests/test_accounts_postgres.py`) discovers every `user_id` column and every
foreign key to `users` from the live Postgres schema, fills each for two users,
deletes one through the API, and asserts none of its ids remain while the other
user's rows do. A new table with a user column is covered automatically.

PLAN §D should be read with this correction; the plan branch itself was not edited.

## Late-test (load) proof for the admin assertion fix

On the first full run (`ea00c36`, Postgres 16, `evidence/full-api-suite-ea00c36-pg16.txt`),
three `test_method_path_and_body_are_bound` cases failed with
`admin_actor_assertion_expired`. Their 60-second tokens were minted in the
parametrize list, i.e. at collection time, so any run that reached them more
than 60 s later (a loaded machine, a slow CI runner) failed. `7920e3d` mints the
token inside the test; expiry and assertions are unchanged; no application code
changed. (The other two failures in that run were Postgres-16-only constraint
tests; they pass on Postgres 18, which staging runs.)

Proof: the suite was run with a **65-second sleep after collection**
(`tools/delay_after_collection.py`, a pytest plugin), longer than the token
lifetime, and passed both times:

- `ae73048` (pre-rebase): 5494 passed, 41 skipped (`evidence/full-api-suite-ae73048-delay65.txt`).
- `793d203` (rebased on S1): **5150 passed, 41 skipped, 0 failed**
  (`evidence/full-api-suite-793d203-pg18-delay65.txt`).

## Skip comparison

Both suites ran locally on a fresh Postgres 18 on port 5544 (some tests hardcode
5544; `TEST_POSTGRES_URL` plus `TEST_POSTGRES_HOST/PORT/USER/PASSWORD` set), with
`-rs` and JUnit XML (`tools/run_suite.sh`, `tools/run_both.sh`).

| Run | Result |
|---|---|
| `origin/staging` `b9d1c21` (`evidence/full-api-suite-staging-b9d1c21-pg18.txt`) | 5012 passed, 41 skipped (same numbers as S1 recorded) |
| S3 `793d203` | 5150 passed, 41 skipped |

`evidence/skip-comparison-793d203-vs-b9d1c21.json` (`tools/compare_skips.py`):
**identical skip set by test id and by reason**, 41 = 41. Only in baseline: none.
Only in S3: none. Same id, different reason: none. **S3 adds no skips.** The 41
are pre-existing environment skips: frozen catalogue snapshots not checked out
(31), no local official snapshot (4), `opcg_test_a`/`opcg_test_b` databases absent (4),
`SEC8B_TEST_POSTGRES_URL` unset (2). The full list with reasons is in the JSON.

Import graph (`evidence/import-graph-check-793d203.json`, base `b9d1c21`,
installed component `a504e47`): snkrdunk and yuyutei **0 changed runtime
inputs**, 0 PR files in either import set, no `app/accounts` module reached,
nothing under `app/models/**`, `settings.py` or requirements touched.

## Environment notes for the next session

- The shared venv (`~/.venvs/cardpirate`) has a stale, non-editable
  `opcg_source_identity` without `raw_payload`. Running the API suite or alembic
  from a worktree needs `PYTHONPATH=<worktree>/packages/opcg_source_identity/src`.
  The venv was not changed.
- Postgres tests need a server on **5544** with `opcg/opcg`; with only
  `TEST_POSTGRES_URL` on another port about 420 tests skip silently.

## Earlier evidence in this folder

From the build session (2026-10-12/13 night): `backups-preflight-1.json`,
`staging-state-preflight-1.json`, `legacy-dry-run-premigration.json` (tables
absent then), `import-graph-check-ea00c36.json`, the two earlier suite logs.

## S1 receipt carried here

The pending PR #111 (S1 handoff) receipt is committed with this change under
`docs/agent/handoff/2026-10-13/collector-v1-s1/evidence/pr111-delivery/`:
`staging-delivery-b9d1c211…` verified 2026-10-13T07:49:09Z, delivery scope
`skip` (docs only), frontend READY at `b9d1c21`, API not rebuilt, migration
`6c2242f6f439`, collectors unchanged at `a504e47`, 0 sale index inputs.

## Pending receipt

This handoff's own PR (docs only, delivery scope expected `skip`, 0 collector
deployments, revision stays `3b7d9c1a5e20`): download its
`staging-delivery-<merge sha>` artifact first in the next session.

## Next

S4 (daily value stage writing `collection_value_points`) and S5 (auth, account
section, flag on) can build on these tables. S2 is independent. Quiet windows
from the newest capacity handoff still apply (19:30-20:30Z no API/migration merge).
