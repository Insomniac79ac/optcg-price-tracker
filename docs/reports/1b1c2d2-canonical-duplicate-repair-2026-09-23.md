# Source Mapping Coverage 1B1C2D2: staging duplicate repair

This tranche preserves historical mapping rows and enforces one current mapping
per non-NULL canonical listing identity. It changes no proposal decision,
candidate, price observation, source integration, or collector schedule.

The server-enforced read-only preflight found 839 mappings, 815 populated
canonical identities, 24 NULL identities, zero supersessions, and exactly two
duplicate-current groups. The four rows and every mapping-ID dependency were
rechecked after the backup and before the one-time data transaction.

The manually created staging Postgres `postgres-volume` backup is
`pre-canonical-duplicate-repair-20260923-161732Z`, ID
`312693a9-ed9b-43d5-aeb5-8aa66738fd7a`, created
`2026-09-23T16:18:37.786Z`. Railway listed it as available with 1,290 MB
referenced and 3 MB incremental. It was neither restored nor modified.

One transaction committed at `2026-09-23T16:28:13.848046+00:00` and changed
only `superseded_at`, `superseded_by_mapping_id`, `supersession_reason`, and
`is_active` on mapping 12 and mapping 16:

| Historical mapping | Current successor | Canonical SNKRDUNK listing | Reason |
| --- | --- | --- | --- |
| 12 | 35 | 104428 | Historical duplicate of canonical SNKRDUNK listing 104428; superseded by exact current mapping 35. |
| 16 | 36 | 93522 | Historical duplicate of canonical SNKRDUNK listing 93522; superseded by exact current mapping 36. |

Mappings 35 and 36 remain exact, approved, and current. No dependent row was
repointed. The pre/post dependency counts were unchanged apart from each
successor receiving one supersession link from its historical row.

Revision `f2c7d91b6a40` has parent `b8e04219d6c3` and adds only
`uq_mapping_current_canonical_listing_identity` on
`(source_id, canonical_source_listing_identity)` with predicate
`superseded_at IS NULL AND canonical_source_listing_identity IS NOT NULL`.
It contains no data repair. The index was applied to staging after the
two-row transaction and verified unique and valid in PostgreSQL.

Read-only post-migration verification found 839 mappings, two superseded
historical rows, zero duplicate-current canonical identities, and 24 NULL
identities. The approved proposal set remains 1128, 1129, and 3815, linked
to mappings 1159, 1158, and 1160 respectively. All four mapping dependency
counts and all proposal totals match the post-repair check. The 24 NULL
identity rows were untouched and remain a separate later audit.

Disposable PostgreSQL tests cover duplicate refusal, alternate URL forms,
historical/current coexistence, NULL identities, rejected-current occupation,
explicit successor lifecycle, index validity, and a stale writer losing the
race without a partial mapping. Backup v13 round trips valid historical chains
and refuses duplicate-current archives; v12 compatibility remains explicit.
