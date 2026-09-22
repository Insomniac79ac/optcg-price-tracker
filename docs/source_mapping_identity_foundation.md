# Canonical mapping identity foundation (1B1C2D1)

This foundation does not repair historical duplicate mappings or decide proposals.
The pilot remains provenance-unresolved; broader approval rollout stays paused.

## Three distinct identities

- Raw `source_url`: evidence and collector fetch configuration, never rewritten by migration.
- `(source_id, canonical_source_listing_identity)`: source listing identity.
- `card_print_id`: authoritative physical-print pricing identity; `card_id` is compatibility only.

`packages/opcg_source_identity` is a dependency-free, standard-library-only Python
package installed normally (not editable) into API, worker and beat. Its public
`canonical_source_listing_identity(source_name, source_url)` uses the former
authoritative parsers: Yuyu's lowercase supported slug plus `:` plus product ID;
SNKRDUNK's numeric ID across `/apparels/` and `/en/trading-cards/`. Query strings,
fragments and tolerated trailing slashes do not change identity. Numeric text is
preserved, including leading zeros, matching the original parser contract.
Unsupported hosts, legacy card-code URLs and missing URLs return None. There is
no network, database, environment, card-code or title inference. API and worker
public parser modules are thin imports; the package's `vectors` is the shared
conformance fixture used by both service tests and image build smoke checks.

## Schema and lifecycle

Revision `b8e04219d6c3`, parent `a7f936027b8f`, adds nullable canonical identity
(varchar 1024), timestamptz superseded_at, RESTRICT self-FK
superseded_by_mapping_id and text supersession_reason. Named lifecycle checks
require either all lifecycle fields NULL or all supplied, a nonblank reason and
inactive state. Self-supersession is forbidden. Review state is preserved.
There is no delete cascade on the ORM relationship.

`ix_mapping_current_listing(source_id, canonical_source_listing_identity,
superseded_at)` is deliberately NON-UNIQUE. The migration backfills only the new
identity column, with the shared parser, using Core SQL to avoid updated_at hooks.
Unparseable rows remain NULL. No supersession metadata is populated.

## Writer and lookup audit

| Path | Previous protection | Foundation contract |
| --- | --- | --- |
| Yuyu ordinary/proposal-aware approval | Parser scan | Shared DB current lookup; existing provenance gates retained |
| SNKRDUNK candidate and exact proposal approval | Parser scan/refusal | Shared DB current lookup; existing print/rejection gates retained |
| Legacy SNKRDUNK manual-match API and exact-approval CLI | Source writer/finder | Same canonical lookup; no generic approval bypass |
| Manual mapping PATCH | Literal URL uniqueness | Server derivation, supported URL requirement, current-listing conflict refusal |
| Watchlist CSV writer | Literal URL upsert | Canonical lookup/deduplication, rejected/exact/conflicting rows protected |
| Worker discovery/CSV apply_match | Card/source lookup | Shared derivation, DB current identity lookup, duplicate refusal, historical/protected rows not overwritten |
| Worker candidate price ingestion | Literal URL variants / first row | Canonical current claim cardinality before priceability; ambiguity writes no price |
| URL canonicalization operational script | Parser only | Current-only selection, canonical duplicate refusal, ORM derivation |
| Official Bandai display-evidence writer | Print/raw URL lookup | Unsupported source identity stays NULL; not a supported listing-approval path |
| Demo seed | Literal placeholder URL | ORM projection leaves intentionally unparseable demo URLs NULL; local demo only |
| Canonical catalogue import/update | No mapping writes | Unchanged: explicitly forbids mapping writes |
| Import validation | Literal URL reporting | Shared current canonical lookup; reports unparseable/duplicate refusal |
| Quality/catalogue/proposal operational reports | Mixed parser/literal reads | Persisted listing identity and superseded exclusion where operational |
| Backup export/restore | v12 generic serialization | v13 lifecycle-aware export; v12 compatibility; target-first restore |
| Evidence/confidence/compatibility-card editors | Do not change URL | Preserve canonical identity; do not infer a new listing |

API ORM events provide a server-side derivation backstop for every ORM creation
and URL/source change. Worker events use the same pure contract, not API code.
Client PATCH input forbids arbitrary identity or lifecycle fields. Core migration
and backup handling explicitly derive rather than trusting archive identity.

The read helper returns zero/one current mapping plus all historical mappings;
more than one current mapping raises `multiple_mappings_for_listing`. Rejected
current rows still occupy the listing. Supported approval writers serialize on
the Source row while uniqueness is intentionally absent. No current lookup
chooses an arbitrary duplicate. Read-only calls need no lock.

Historical-only means no implicit reactivation/repoint: a new current row may be
created only by the ordinary source-specific writer after all approval gates.
If a historical row already owns the exact raw URL, the retained literal URL
constraint refuses insertion. This phase does not rewrite history to free that
URL; an operator must address it in a separately authorized lifecycle tranche.

Both dedicated collectors and worker price gates explicitly require
superseded_at IS NULL, even for hypothetical invalid active historical rows.
Schedules, shard assignment, fair ordering and fetch behavior are unchanged.
Quality GET adds an unfiltered `global_listing_integrity` block, separate from
filtered/paginated quality totals, with duplicate-current groups, historical,
NULL identity, current exact, current compatibility and broken counts. Mapping
list/detail and quality rows expose lifecycle metadata without hiding history.

## Backup compatibility

New exports are v13 because supersession is operationally significant: v12
runtimes must refuse new archives rather than ignore lifecycle and resurrect
history. New runtime explicitly accepts v12 and v13. Missing additive fields
default to NULL; canonical identity is recomputed from trusted source name/raw
URL. Contradictory supplied canonical identity is refused. Duplicate current
identities are counted and warned, not normalized or silently repaired.
Supersession chains restore target-first, preserving lifecycle checks throughout;
cycles/missing/self targets are refused. Merge cannot silently reactivate an
already-superseded destination. Existing selective-registry coverage is unchanged:
this is not a proposal persistence or full-database backup redesign. Railway
volume backups are not the selective JSON contract and remain untouched.

## Packaging and validation

Install for host tests/migrations with
`python -m pip install --no-deps ./packages/opcg_source_identity`.
Makefile test targets and host verification install it explicitly. Compose API,
worker and beat use repository-root contexts with explicit service Dockerfiles;
Railway already uses root context. All five relevant Dockerfiles copy the package
to `/opt/opcg_source_identity` and install normally before application imports.
The root `.dockerignore` allowlists service/package trees and excludes secrets,
env files, caches, Git state, evidence, snapshots and node_modules. No runtime
commands, dashboard configuration, trigger/watch paths or schedules are changed.
Existing Railway watch patterns cover service/Dockerfile changes in this tranche.
A future package-only change must also update each consumer's watched integration
file (or obtain separate authorization for watch-path changes); it must not assume
that package paths alone trigger every consumer deployment.
CI builds Compose and the Railway API/worker/beat images; each image build runs
the same import/vector smoke assertions. No local image builds are necessary.

## Reviewer privacy and future provenance

The reusable browser masking helper displays first local-part character + `***`
and domain; malformed identifiers display a generic label, missing values show
Not returned. Both terminal and success views use it; rendered HTML tests cover
attributes as well as visible text. Full database/server audit identity,
idempotency comparison and actor assertion are unchanged.

A later provenance tranche should transactionally record group, alternative and
resulting mapping IDs; actor identifier and masked display actor; decision time;
actor assertion jti hash or decision request ID; proxy/backend correlation ID;
idempotent replay flag; route/channel and outcome. Never store ADMIN_TOKEN, actor
JWT, session cookie, password or raw IP without an established privacy-safe need.
Do not attempt to reconstruct or repeat the three historical pilot approvals.

## Separate follow-up repair (NOT authorized here)

1. Recheck pilot/duplicate invariants and take a fresh staging backup immediately
   before repair. Preserve all earlier backups, including forensic
   `12f9ef8d-8f81-4de8-ba24-ffa511f20ce1`.
2. In a separately authorized transaction retain 35 and 36 as current exact rows;
   supersede 12 by 35 and 16 by 36 with explicit reason/time and inactive state.
   Preserve rejected/needs_review history and all observation/snapshot lineage.
   No dependent row requires repointing according to the C4 forensic audit.
3. Verify zero duplicate CURRENT identities and unchanged pilot/historical data.
4. Add a partial UNIQUE index on (source_id, canonical_source_listing_identity)
   WHERE superseded_at IS NULL AND canonical_source_listing_identity IS NOT NULL.
   Include rejected and inactive current rows: their decisions must still block
   silent replacement. Do not predicate uniqueness on approved/active status.
5. Harden restore duplicate-current validation for that schema and rerun writer,
   collector, backup and PostgreSQL concurrency tests. Approval rollout remains
   paused pending a separate provenance/rollout decision.

Protected staging backup inventory from C4 (not a screenshot transcription):

| ID | Label | Created UTC | Referenced MB | Expiry UTC |
| --- | --- | --- | --- | --- |
| ae70145f-812a-4b34-b73e-cdedbdc30d71 | Pre-Security-Patch Backup | 2026-08-29 12:00:25.700 | 197 | 2026-09-28 12:00:25.337 |
| a744b757-195b-4c57-a332-9162db040911 | Online resize to 10000MB | 2026-09-16 01:30:58.208 | 476 | none listed |
| 42b6895c-8c10-454f-80a3-ee5e458c3024 | pre-source-mapping-foundation-20260919-143614Z | 2026-09-19 14:41:10.513 | 1148 | none listed |
| 70bdf69c-579a-4ad1-9580-1b000193c06d | post-source-mapping-materialization-20260921-034047Z | 2026-09-21 03:41:22.788 | 1211 | none listed |
| 12f9ef8d-8f81-4de8-ba24-ffa511f20ce1 | post-exact-approval-pilot-forensic-20260922-095249Z | 2026-09-22 10:09:54.807 | 1251 | none listed |
