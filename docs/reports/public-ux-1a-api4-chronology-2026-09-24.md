# Public UX 1A-API4: release chronology verification

PR [#13](https://github.com/Insomniac79ac/optcg-price-tracker/pull/13) adds public catalogue contracts and verified release chronology. Final merge and Git-triggered staging deployment evidence is recorded in the PR. The frontend tranche is separate.

## Durable input

The tracked [receipt](../evidence/public-ux-1a-release-dates-2026-09-24.json) is the migration input authority. Its canonical accepted mapping was recomputed and matched to all 59 frozen migration tuples. No original gitignored evidence directory, Bandai request, archive rebuild, or R2 request was used in API4.

- Receipt status: `DURABLE_GET_AND_RECOVERY_VERIFIED`; independent recovery passed.
- Accepted products/dates/conflicts: **59 / 59 / 0**; OP 17, EB 4, PRB 2, ST 36.
- Acquisition records/raw payloads/source associations: **75 / 67 / 117**.
- Private object: `official-evidence/bandai_jp/release-dates/2026-09-24/sha256/247eaa5fd75590c49f8323dc0662c54cff91820df5200236ffe21f7616d69e54.tar.gz`.
- Archive SHA-256: `247eaa5fd75590c49f8323dc0662c54cff91820df5200236ffe21f7616d69e54`.
- Accepted mapping SHA-256: `313f1d4bd09865d6198bc5949000f38065fce2daea2d723d97aa34e4f1412090`.

## Schema and transaction

Linear revision `c4e9a2b7816d` follows `f2c7d91b6a40`. It adds nullable `released_on DATE`, nullable `release_date_source VARCHAR(32)`, then constraints, then the backfill. A date requires non-NULL, nonblank provenance. The source vocabulary is restricted to the two classifications actually in the receipt. Undated rows are valid. Downgrade removes only the two chronology constraints and two columns.

Identity matching uses `(source_catalogue, official_code)`. SQLAlchemy Core updates bypass application update hooks. `source_catalogue`, `official_code`, `display_name`, `first_seen_name`, `source_series_id`, `source_url`, `verification_status`, `created_at`, and `updated_at` were preserved.

Preflight at 2026-09-24T16:30:36Z verified server-enforced `transaction_read_only=on`, revision `f2c7d91b6a40`, 65 products, 59 exact receipt identities, six uncoded products, and absent chronology columns. It rolled back and closed. The inventory and digest were rechecked immediately before DDL and again under transaction locks.

Migration committed at **2026-09-24T16:45:58Z**, from reviewed PR head `06068cb4c69d108acc1556175d699b5597ca558f`. Alembic executed only the new revision inside the guarded transaction. Counts, all date/source pairs, and protected values were checked before commit.

Postflight at 2026-09-24T16:46:34Z used a fresh server-enforced read-only session: revision `c4e9a2b7816d`, total **65**, dated **59**, provenance populated **59**, undated **6**, chronology violations **0**. All 59 pairs matched the receipt; all six undated identities matched preflight. It rolled back and closed.

Protected fields plus IDs had the same count and SHA-256 before and after: `533e3db37dbdde23df3d7a01c82b8b1d9199f8b6c8a50a005a31bbba56d64cf3`. Provenance counts: 58 `DATE_VERIFIED_CORROBORATED`; one `DATE_VERIFIED_SINGLE_SOURCE` (EB-04).

## Six retained undated products

| ID | Name | Date/source |
|---|---|---|
| 225 | 1st ANNIVERSARY SET | NULL / NULL |
| 226 | スタンダードバトルパック Vol.3 | NULL / NULL |
| 227 | スタンダードバトルパック2022 Vol.1 | NULL / NULL |
| 228 | スタンダードバトルパック2022 Vol.2 | NULL / NULL |
| 229 | プレミアムカードコレクション - ベストセレクションvol.1 - | NULL / NULL |
| 230 | プレミアムカードコレクション 25周年エディション | NULL / NULL |

## Release read contract

Each item exposes `release_product_id`, `official_code`, `display_name`, `verification_status`, `print_count`, `released_on`, `chronology_available`, and `release_date_source`. Existing `source_catalogue` and `created_at` fields remain. `source_url` is absent. Item chronology is exactly `released_on IS NOT NULL`. Endpoint metadata is `chronology_available=true` and `ordering_basis=released_on_desc_then_deterministic_fallback`.

Ordering is `released_on DESC NULLS LAST`, `source_catalogue ASC`, `official_code ASC NULLS LAST`, `display_name ASC`, `id ASC`. Same-day tie breakers express no meaningful chronological priority. Six undated products follow all 59 dated products.

The reviewed read model was executed against staging with server-enforced read-only access before merge. It returned 65 public releases and the following top 30:

| Position | Product | Release date |
|---|---|---|
| 1 | OP-17 | 2026-08-22 |
| 2 | ST-31 | 2026-07-11 |
| 3 | ST-32 | 2026-07-11 |
| 4 | ST-33 | 2026-07-11 |
| 5 | ST-34 | 2026-07-11 |
| 6 | ST-35 | 2026-07-11 |
| 7 | ST-36 | 2026-07-11 |
| 8 | OP-16 | 2026-05-30 |
| 9 | ST-30 | 2026-04-11 |
| 10 | OP-15 | 2026-02-28 |
| 11 | EB-04 | 2026-01-31 |
| 12 | ST-29 | 2025-12-20 |
| 13 | OP-14 | 2025-11-22 |
| 14 | EB-03 | 2025-10-25 |
| 15 | OP-13 | 2025-08-23 |
| 16 | PRB-02 | 2025-07-26 |
| 17 | ST-23 | 2025-06-28 |
| 18 | ST-24 | 2025-06-28 |
| 19 | ST-25 | 2025-06-28 |
| 20 | ST-26 | 2025-06-28 |
| 21 | ST-27 | 2025-06-28 |
| 22 | ST-28 | 2025-06-28 |
| 23 | OP-12 | 2025-05-31 |
| 24 | ST-22 | 2025-04-26 |
| 25 | OP-11 | 2025-03-01 |
| 26 | EB-02 | 2025-01-25 |
| 27 | ST-21 | 2024-12-21 |
| 28 | OP-10 | 2024-11-30 |
| 29 | OP-09 | 2024-08-31 |
| 30 | PRB-01 | 2024-07-27 |

## API compatibility and validation

Repeatable rarity/treatment parameters retain scalar compatibility and OR semantics within each filter. Authoritative membership uses `CardPrint.release_product_id`, including mixed-code OP17 reprints. Legacy set URLs remain valid; a conflicting set and release ID returns 400. `created_desc` remains Atlas ingestion chronology, with stable timestamp/ID pagination. Legacy sort tokens and existing response fields remain supported. OpenAPI tests verify these contracts and the new release fields.

- 155 focused model, release, filter, print, OpenAPI, and PostgreSQL migration tests passed.
- 28 private archive/evidence tests passed.
- Disposable PostgreSQL upgrade/downgrade/upgrade proved 59 dated/six NULL rows, constraints, unchanged protected values, and exact schema restoration on downgrade.
- Compilation, dependency consistency, whitespace validation, and secret scanning passed.
- Full CI exposed historical test fixtures that loaded current ORM models against old schemas. Their disposable databases now advance to the current Alembic head; historical migration-cycle assertions remain pinned. The image-mirror test now checks its own storage/schema boundary instead of banning unrelated evidence hashes from every migration. These are test-only compatibility changes.
- Existing deployed API health and scalar rarity/legacy set requests returned 200 after migration, before merge; no API error logs appeared in the observed post-migration window.
- Existing staging frontend home and cards pages with scalar rarity, legacy set, and old sort URLs returned 200 with no browser page errors. Source images and external browser requests were blocked; this check verifies rendering/data compatibility, not image delivery.

## Backup

Exactly one new manual backup targeted `glistening-peace / staging / Postgres / postgres-volume`.

- Label: `pre-release-chronology-20260924-164224Z`.
- Backup ID: `de6655a3-fbf1-4c6c-a881-1d06f56e2aaa`.
- Created: `2026-09-24T16:42:24.916Z`.
- Completion evidence: Railway listed the named backup as available at `2026-09-24T16:44:01.749735Z`, before migration, with external snapshot ID `vs_1790268144830_u9do4d16xvqcwfq7`.
- Referenced size: **1,323 MB**. Incremental size was returned as NULL/unavailable.
- Backup was not restored, deleted, or renamed.

## Scope and collector observation

No Bandai/source fetch, archive rebuild, proposal/mapping/candidate mutation, manual collector, production access, Railway/Cloudflare configuration change, pricing change, or Market Index change occurred. Railway operations explicitly targeted staging services. The API, worker, beat, and collector deployments retained their pre-migration states while the PR remained unmerged.

Batch 1 observation remained independent. The most recent SNKRDUNK scheduled run inspected was the pre-existing 11:20 UTC batch, completed at 11:35:09 UTC with 70 attempts, 65 identity verified, and five failures (`partial_failure`). That baseline was not repaired or rerun here. No scheduled collector activity occurred in the observed migration window.
